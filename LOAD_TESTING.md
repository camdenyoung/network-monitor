# Synthetic capacity testing

Run the simulator and HTTP load generator on a **different computer** from the
Raspberry Pi. During measurement the Pi runs one ordinary monitoring instance;
it does not run device emulators, a history generator or a second monitoring
instance. The test uses the production ping/SNMP/Modbus clients, polling scheduler,
SQLite schema, dashboard queries and retention cleanup.

The tools are on `codex/synthetic-load-test`. They require Docker Compose on the Pi
and simulator machine. The external HTTP probe uses Python 3.11+ standard-library
modules and needs no package installation. Both machines need this checkout:

```sh
git fetch origin
git switch --track origin/codex/synthetic-load-test
```

If the branch already exists locally, use `git switch codex/synthetic-load-test`
and `git pull origin codex/synthetic-load-test`.

The disposable monitor publishes port **8081**, with its own Compose project and
`benchmark-data` volume. Its accounts, inventory, projects and generated history
are independent of the normal `compose.yaml` installation. The seeder refuses to
write an existing database, and the HTTP probe refuses an unmarked installation.
Notifications are disabled in the benchmark dataset.

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
