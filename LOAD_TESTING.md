# Synthetic capacity testing

Run the simulator and HTTP load generator on a **different computer** from the
Raspberry Pi. During measurement the Pi runs one ordinary monitoring instance;
it does not run device emulators, a history generator or a second monitoring
instance. The test uses the production ping/SNMP/Modbus clients, polling scheduler,
SQLite schema, dashboard queries and retention cleanup.

The tools are on `codex/load-test-improvements`. They require Docker Compose on the Pi
and simulator machine. The external HTTP probe uses Python 3.11+ standard-library
modules and needs no package installation. Both machines need this checkout:

```sh
git fetch origin
git switch --track origin/codex/load-test-improvements
```

If the branch already exists locally, use `git switch codex/load-test-improvements`
and `git pull origin codex/load-test-improvements`.

The disposable monitor publishes port **8081**, with its own Compose project and
`benchmark-data` volume. Its accounts, inventory, projects and generated history
are independent of the normal `compose.yaml` installation. The seeder refuses to
write an existing database, and the HTTP probe refuses an unmarked installation.
Notifications are disabled in the benchmark dataset.

## Updating an existing week-history test

Build 45 incorporates the fixes validated in test Builds 42–43: avoid full-history
scans that could leave dashboards empty or showing Unknown / paused, and bound
the first readings after startup or deployment resume. Keep the generated database; do not seed again or
start a new deployment. On the Pi, from the repository directory:

```sh
sudo docker compose -p network-monitor-loadtest -f compose.loadtest.yaml stop benchmark-monitor
git pull origin codex/load-test-improvements
sudo docker compose -p network-monitor-loadtest -f compose.loadtest.yaml up -d --build benchmark-monitor
sudo docker compose -p network-monitor-loadtest -f compose.loadtest.yaml logs -f benchmark-monitor
```

The first upgraded startup builds `sample_current` and `sample_expiry` indexes.
A large database needs additional free disk space for the indexes and SQLite's
build workspace. Duration depends on storage and dataset size; CPU/disk activity
is expected. Wait for both `History index ... ready` messages and successful API
responses before measuring. Press Ctrl+C to leave the log view; this does not
stop the container. Subsequent restarts reuse the indexes. The same named volume
retains users, hosts, project, deployment and all unexpired generated history.
Never use `down -v` unless you intend to delete that test database.

## 1. Start synthetic devices on the other computer

From this repository on a laptop/server on the same LAN:

```sh
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml --profile simulator up -d --build simulator
```

The simulator exposes real SNMP v2c on UDP **161** and Modbus TCP on **502**.
Its machine must also answer ICMP ping from the Pi; blocked ping would skip
the service workload and is a test failure, not a capacity pass.
Those ports must be available and reachable from the Pi. Find this computer's
LAN IPv4 address; use it as `--simulator` below. All virtual inventory hosts share
that address; synthetic OIDs identify SNMP hosts, and unit IDs identify Modbus
hosts. Host ping therefore remains up when a service is made unresponsive.

## 2. Prepare a fresh test monitor on the Pi

First build the image, then seed the separate volume **before starting the test
monitor**. Replace `192.168.1.50` with the simulator computer's address:

```sh
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml build benchmark-monitor
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml run --rm --no-deps benchmark-monitor python -m tools.load_test seed --database /data/monitor.sqlite3 --simulator 192.168.1.50 --hosts 150 --services 5 --users 3
```

This creates 150 hosts, **750 additional services plus 150 automatic ping checks**.
By default all additional services use SNMP. Add `--modbus-services 1` to make
one of each host's five services a Modbus PSU voltage check instead.

For the timed test, stop the normal monitoring container so a second instance
does not compete for Pi resources. This preserves its normal data volume:

```sh
docker compose stop monitor
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml up -d benchmark-monitor
```

Open `http://PI_ADDRESS:8081` to inspect the synthetic dashboard. The disposable
administrator login is **admin / benchmark-only-password**. Viewer accounts
`loadtest-01` through `loadtest-03` use the same benchmark password. These are
benchmark credentials only.

## 3. Generate dashboard load externally

On the laptop/server, replace `192.168.1.60` with the Pi's LAN address:

```sh
python3 -m tools.load_test probe --url http://192.168.1.60:8081 --duration 600 --warmup 30 --users 3 --report fresh-healthy.json
```

This simulates separate signed-in users fetching the real Admin/Status APIs every
ten seconds. The administrator also requests the user/provider settings normally
loaded by the admin page. It does not click destructive controls or send messages.

The report includes:

- Dashboard request counts, errors, median/p95/maximum latency.
- Sample intervals observed across the 900 checks, interval coverage and freshness.
- Live monitor version/build, dataset ID, host/service counts, seeded history and generator platform.
- `PASS`, `FAIL` or `INCONCLUSIVE`, with reasons and the targets used.

Initial targets are dashboard p95 at most **2 seconds**, maximum observed check
interval **30 seconds**, and no missing/stale samples beyond the app's **60-second**
freshness threshold. They are configurable with `--maximum-dashboard` and
`--maximum-interval`; these are explicit test targets, not a guaranteed product SLA.
A pass also requires the workload to remain enabled, no blocked services, and
no unexpected unreachable checks. A pass requires intervals observed for at least 95% of checks. A short test that
has not seen enough updates cannot pass.

The current application waits 15 seconds **after** each polling round; do not
interpret the nominal 15-second delay as a precise sample interval. Interval
measurements come from dashboard snapshots: if the probe misses intermediate
samples, the observed gap is an upper bound, not a scheduler trace.

HTTP tests measure server/database responsiveness, not browser JavaScript, persistent
event streams or browser rendering. Use a
real browser alongside the probe to assess the 150-host UI. Pi CPU/RAM and storage
I/O are not inferred from the laptop; `docker stats` on the Pi can show container
resource usage. Note whether the Pi uses microSD or SSD when comparing results.

## 4. Repeat with a week's history

A fresh-database pass is insufficient. Stop and remove **only the benchmark
project's disposable volume**, then seed seven days of history:

```sh
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml down -v
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml run --rm --no-deps benchmark-monitor python -m tools.load_test seed --database /data/monitor.sqlite3 --simulator 192.168.1.50 --hosts 150 --services 5 --users 3 --history-days 7 --history-interval 15
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml up -d benchmark-monitor
```

This generates **36,288,000 real SQLite sample rows**, including ping, using the
normal schema and indexes. Generation can take substantial time and disk space;
progress and actual database size are printed. Generation is completed before
measurement, and must not run alongside the timed test. It does not claim that
this many rows have already been verified to perform well on your Pi.

Run the external probe again:

```sh
python3 -m tools.load_test probe --url http://192.168.1.60:8081 --duration 600 --warmup 30 --users 3 --report week-healthy.json
```

After the timed run, collect actual database size and row count on the Pi:

```sh
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml exec benchmark-monitor python -m tools.load_test inspect --database /data/monitor.sqlite3
```

`--history-days 30` can exercise the retention ceiling, but is approximately
155.5 million sample rows at this density. Start with the realistic seven-day run.

## 5. Slow responses, service timeouts and flapping

Change the simulator on the external computer, not the Pi:

```sh
BENCHMARK_LATENCY_MS=100 docker compose -p network-monitor-loadtest -f compose.loadtest.yaml --profile simulator up -d --force-recreate simulator
```

For 10% of services not replying while their hosts still answer ping:

```sh
BENCHMARK_SCENARIO=timeouts BENCHMARK_FAILURE_PERCENT=10 docker compose -p network-monitor-loadtest -f compose.loadtest.yaml --profile simulator up -d --force-recreate simulator
```

Run a new ten-minute probe with `--scenario timeouts` (or `--scenario flapping`
for the flapping run) and save a different report filename; existing reports are never overwritten. Timeout selection
is deterministic by virtual host/service. SNMP responses are dropped and Modbus
connections stop responding, so the **real production timeouts** are measured.

For alternating healthy/critical values on 10% of services:

```sh
BENCHMARK_SCENARIO=flapping BENCHMARK_FAILURE_PERCENT=10 docker compose -p network-monitor-loadtest -f compose.loadtest.yaml --profile simulator up -d --force-recreate simulator
```

The default flap period is 30 seconds. Provider credentials are absent, so no real
Telegram/WhatsApp messages are sent. Inspect issues/flap flags in the test dashboard.

Healthy, slow and timeout tests with fresh and week-sized history are the minimum
useful matrix. Multiple virtual devices behind one address do not validate vendor
MIB compatibility, 150 physical network paths or independent ICMP host failures.
These are capacity tests, not substitutes for eventual equipment integration tests.

## Finish

On the Pi, stop the test monitor and restart the normal installation:

```sh
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml down
docker compose up -d monitor
```

On the simulator computer:

```sh
docker compose -p network-monitor-loadtest -f compose.loadtest.yaml --profile simulator down
```

Keep the JSON reports and measured database size. Those results, on the actual Pi
and storage, determine whether this build meets the required workload and where
optimisation is needed. Running everything on one machine is only a smoke test;
it cannot establish Raspberry Pi capacity.

## Recorded Raspberry Pi 5 results

The user ran the simulator and three HTTP users on a separate Windows 11 AMD64
server. The Pi 5 ran Build 43 with 150 hosts, 750 SNMP services and 150 automatic
ping checks, against 36,288,000 generated history rows representing seven days.
Build 45 integrates the same polling/history fixes onto v0.3.2.

| Scenario | Admin API p95 | Status API p95 | Maximum observed check interval | Result |
| --- | ---: | ---: | ---: | --- |
| Healthy | 0.280 s | 0.325 s | 23.09 s | PASS |
| 10% service timeouts | 0.250 s | 0.329 s | 25.87 s | PASS |
| Flapping values | 0.304 s | 0.327 s | 22.05 s | PASS |

Each measurement ran for ten minutes after warmup, with 100% interval coverage,
100% fresh readings and no HTTP errors. The timeout run observed 75 unreachable
services, as intended. These results support the tested SNMP workload, rather
than every possible failure pattern. They do not measure browser rendering,
CPU/RAM usage, live provider delivery, independent host failures, Modbus capacity,
a continuous seven-day run, or correctness of flap suppression itself.
