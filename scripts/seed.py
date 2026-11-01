#!/usr/bin/env python3
"""Deterministic seed script for the unofficial migration demo.

Generates a fictional legacy data-warehouse estate ("Granite Peak Outfitters",
a made-up retailer) with Teradata BTEQ, SQL Server T-SQL and Oracle PL/SQL
modules, each with a risk score, a legacy code excerpt, the converted
Snowflake excerpt, remediation notes and generated tests.

All names, numbers and code are synthetic. Run:
    python3 scripts/seed.py
Writes data/seed.json and data/seed.js (window.SEED = ...).
"""
import json
import os
import random
import re

SEED = 20261021
rng = random.Random(SEED)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- entities
ENTITIES = [
    # domain, entity, key, attr, measure, table
    ("SALES", "order", "order_id", "channel_cd", "net_amount", "fct_order"),
    ("SALES", "return", "return_id", "reason_cd", "refund_amount", "fct_return"),
    ("CUSTOMER", "customer", "customer_id", "segment_cd", "lifetime_value", "dim_customer"),
    ("CUSTOMER", "loyalty", "member_id", "tier_cd", "points_balance", "dim_loyalty_member"),
    ("INVENTORY", "stock", "sku_id", "warehouse_cd", "on_hand_qty", "fct_stock_snapshot"),
    ("INVENTORY", "product", "product_id", "category_cd", "list_price", "dim_product"),
    ("FINANCE", "invoice", "invoice_id", "currency_cd", "invoice_amount", "fct_invoice"),
    ("FINANCE", "account", "account_id", "account_type_cd", "amount_usd", "dim_gl_account"),
    ("LOGISTICS", "shipment", "shipment_id", "carrier_cd", "freight_cost", "fct_shipment"),
    ("LOGISTICS", "route", "route_id", "region_cd", "distance_km", "dim_route"),
    ("SUPPLY", "supplier", "supplier_id", "country_cd", "spend_usd", "dim_supplier"),
    ("SUPPLY", "purchase", "po_id", "buyer_cd", "po_amount", "fct_purchase_order"),
]

TEAMS = {
    "SALES": "Commerce Data", "CUSTOMER": "Customer 360", "INVENTORY": "Merch Analytics",
    "FINANCE": "Finance Systems", "LOGISTICS": "Fulfillment Data", "SUPPLY": "Sourcing Analytics",
}
REVIEWERS = ["Priya Natarajan", "Marcus Okafor", "Lena Vogel", "Tomas Ruiz", "Aiko Sato", "Dana Whitfield"]

# ---------------------------------------------------------------- templates
# Markers: legacy lines end with  --@issue:key[,key]
#          target lines end with  --@det:key  (deterministic engine)
#                                 --@ai:key   (AI remediation)
TEMPLATES = {}

TEMPLATES["tsql_upsert"] = dict(
    dialect="SQL Server T-SQL", obj="Stored procedure", level=0, base_cov=0.91,
    name="{{schema}}.usp_upsert_{{entity}}", path="legacy/sqlserver/procs/usp_upsert_{{entity}}.sql",
    legacy="""CREATE PROCEDURE {{schema}}.usp_upsert_{{entity}}
    @load_date DATETIME = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @rows INT;
    SET @load_date = ISNULL(@load_date, GETDATE());   --@issue:isnull

    SELECT s.{{key}}, s.{{attr}}, ISNULL(s.{{measure}}, 0) AS {{measure}},   --@issue:isnull
           CONVERT(VARCHAR(8), s.updated_at, 112) AS load_key   --@issue:convert
    INTO #stg_{{entity}}   --@issue:temp
    FROM stg.{{entity}}_raw s WITH (NOLOCK)   --@issue:nolock
    WHERE s.updated_at >= DATEADD(day, -1, @load_date);

    BEGIN TRY   --@issue:trycatch
        MERGE {{schema}}.{{table}} AS t
        USING #stg_{{entity}} AS s
           ON t.{{key}} = s.{{key}}
        WHEN MATCHED THEN UPDATE
             SET t.{{attr}} = s.{{attr}}, t.{{measure}} = s.{{measure}}, t.updated_at = GETDATE()
        WHEN NOT MATCHED THEN INSERT ({{key}}, {{attr}}, {{measure}}, updated_at)
             VALUES (s.{{key}}, s.{{attr}}, s.{{measure}}, GETDATE());
        SET @rows = @@ROWCOUNT;   --@issue:rowcount
        INSERT INTO audit.load_log (proc_name, row_count, run_at)
        VALUES ('usp_upsert_{{entity}}', @rows, GETDATE());
    END TRY
    BEGIN CATCH
        RAISERROR('usp_upsert_{{entity}} failed: %s', 16, 1, ERROR_MESSAGE());   --@issue:raiserror
    END CATCH
END""",
    target="""CREATE OR REPLACE PROCEDURE {{schema}}.usp_upsert_{{entity}}(load_date TIMESTAMP_NTZ DEFAULT NULL)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    rows_affected INTEGER;
    run_date TIMESTAMP_NTZ;
BEGIN
    run_date := COALESCE(:load_date, CURRENT_TIMESTAMP());   --@det:isnull

    CREATE OR REPLACE TEMPORARY TABLE stg_{{entity}} AS   --@ai:temp
    SELECT s.{{key}}, s.{{attr}}, COALESCE(s.{{measure}}, 0) AS {{measure}},   --@det:isnull
           TO_CHAR(s.updated_at, 'YYYYMMDD') AS load_key   --@det:convert
    FROM stg.{{entity}}_raw s   --@ai:nolock
    WHERE s.updated_at >= DATEADD(day, -1, :run_date);

    MERGE INTO {{schema}}.{{table}} AS t
    USING stg_{{entity}} AS s
       ON t.{{key}} = s.{{key}}
    WHEN MATCHED THEN UPDATE
         SET t.{{attr}} = s.{{attr}}, t.{{measure}} = s.{{measure}}, t.updated_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT ({{key}}, {{attr}}, {{measure}}, updated_at)
         VALUES (s.{{key}}, s.{{attr}}, s.{{measure}}, CURRENT_TIMESTAMP());
    rows_affected := SQLROWCOUNT;   --@ai:rowcount
    INSERT INTO audit.load_log (proc_name, row_count, run_at)
    VALUES ('usp_upsert_{{entity}}', :rows_affected, CURRENT_TIMESTAMP());
    RETURN 'OK: ' || rows_affected;
EXCEPTION   --@ai:trycatch
    WHEN OTHER THEN
        INSERT INTO audit.load_error (proc_name, err_msg, run_at)   --@ai:raiserror
        VALUES ('usp_upsert_{{entity}}', :SQLERRM, CURRENT_TIMESTAMP());   --@ai:raiserror
        RAISE;   --@ai:raiserror
END;
$$;""",
    notes={
        "isnull": ("det", "ISNULL to COALESCE", "Rule-based rewrite. Same semantics for two arguments."),
        "convert": ("det", "CONVERT style 112 to TO_CHAR", "Style code 112 (yyyymmdd) maps to the format string 'YYYYMMDD'."),
        "temp": ("ai", "SELECT INTO #temp table", "The engine flagged SELECT ... INTO #temp as having no direct equivalent. Devin rewrote it as a session-scoped TEMPORARY TABLE built with CTAS, so it is dropped with the session the way #temp was."),
        "nolock": ("ai", "WITH (NOLOCK) hint", "Removed. Snowflake reads from a consistent snapshot, so the dirty-read hint is not needed. The PR description notes this as an intentional behavior change: no more uncommitted reads."),
        "trycatch": ("ai", "TRY/CATCH block", "Mapped to a Snowflake Scripting EXCEPTION handler that wraps the whole body, so the temp-table build is covered too."),
        "rowcount": ("ai", "@@ROWCOUNT after MERGE", "Replaced with SQLROWCOUNT, read right after the MERGE. A generated test checks that the audit row count matches inserted + updated rows."),
        "raiserror": ("ai", "RAISERROR severity 16", "No severity levels in Snowflake. Devin logs to audit.load_error, then re-raises so the scheduler still marks the job as failed. The legacy behavior was to fail the job, so this keeps it."),
    },
    tests=[
        ("Row-count parity with legacy snapshot", "parity"),
        ("Checksum parity on {{measure}}", "parity"),
        ("NULL {{measure}} lands as 0", "edge"),
        ("Second run is idempotent (0 net changes)", "behavior"),
        ("Audit row_count equals MERGE rows", "behavior"),
        ("Failing source logs to audit.load_error and raises", "error"),
    ],
)

TEMPLATES["bteq_load"] = dict(
    dialect="Teradata BTEQ", obj="BTEQ script", level=0, base_cov=0.84,
    name="ld_{{entity}}_feed.btq", path="legacy/teradata/bteq/ld_{{entity}}_feed.btq",
    legacy=""".RUN FILE = /etl/secure/logon_batch.btq;   --@issue:logon
.SET ERRORLEVEL 3807 SEVERITY 0

CREATE MULTISET VOLATILE TABLE vt_{{entity}} AS (   --@issue:volatile
  SEL {{key}}, {{attr}}, {{measure}}, event_ts   --@issue:sel
  FROM stg.{{entity}}_feed
  QUALIFY ROW_NUMBER() OVER (PARTITION BY {{key}} ORDER BY event_ts DESC) = 1
) WITH DATA PRIMARY INDEX ({{key}}) ON COMMIT PRESERVE ROWS;   --@issue:volatile

.IF ERRORCODE <> 0 THEN .GOTO LOAD_FAILED;   --@issue:errorcode

DEL FROM {{schema}}.{{table}} WHERE {{key}} IN (SEL {{key}} FROM vt_{{entity}});   --@issue:sel
INS INTO {{schema}}.{{table}}   --@issue:sel
SEL {{key}}, {{attr}}, ZEROIFNULL({{measure}}), CAST(event_ts AS DATE FORMAT 'YYYY-MM-DD')   --@issue:format
FROM vt_{{entity}};

.IF ERRORCODE <> 0 THEN .GOTO LOAD_FAILED;   --@issue:errorcode
COLLECT STATISTICS ON {{schema}}.{{table}} COLUMN ({{key}});   --@issue:stats
.QUIT 0;
.LABEL LOAD_FAILED   --@issue:errorcode
.QUIT 8;""",
    target="""-- Scheduled as a Snowflake task owned by role ETL_BATCH (replaces BTEQ logon)   --@ai:logon
EXECUTE IMMEDIATE $$
BEGIN
  CREATE OR REPLACE TEMPORARY TABLE vt_{{entity}} AS   --@det:volatile
  SELECT {{key}}, {{attr}}, {{measure}}, event_ts   --@det:sel
  FROM stg.{{entity}}_feed
  QUALIFY ROW_NUMBER() OVER (PARTITION BY {{key}} ORDER BY event_ts DESC) = 1;

  BEGIN TRANSACTION;   --@ai:errorcode
  DELETE FROM {{schema}}.{{table}} WHERE {{key}} IN (SELECT {{key}} FROM vt_{{entity}});   --@det:sel
  INSERT INTO {{schema}}.{{table}}   --@det:sel
  SELECT {{key}}, {{attr}}, ZEROIFNULL({{measure}}), TO_DATE(CONVERT_TIMEZONE('America/Denver', event_ts))   --@ai:format
  FROM vt_{{entity}};
  COMMIT;
  -- COLLECT STATISTICS dropped: Snowflake keeps micro-partition metadata automatically   --@ai:stats
  RETURN 'OK';
EXCEPTION   --@ai:errorcode
  WHEN OTHER THEN
    ROLLBACK;   --@ai:errorcode
    RAISE;   --@ai:errorcode
END;
$$;""",
    notes={
        "logon": ("ai", "BTEQ .RUN logon file", "Logon scripts are not carried over. The job runs as a Snowflake task under a service role, and credentials stay out of the code."),
        "volatile": ("det", "MULTISET VOLATILE TABLE", "Rule-based rewrite to TEMPORARY TABLE. PRIMARY INDEX and ON COMMIT PRESERVE ROWS have no meaning in Snowflake and are dropped."),
        "sel": ("det", "SEL / DEL / INS abbreviations", "Expanded to SELECT / DELETE / INSERT."),
        "errorcode": ("ai", ".IF ERRORCODE / .GOTO control flow", "BTEQ branches on the error code after each step. Devin wrapped the delete + insert in one transaction with an EXCEPTION handler, so a failed insert no longer leaves the table half-deleted. That was a latent bug in the legacy script."),
        "format": ("ai", "CAST ... AS DATE FORMAT", "The FORMAT clause only affects display in Teradata. event_ts arrives as TIMESTAMP_LTZ in Snowflake, so Devin converts to the business timezone first. A generated test covers the midnight boundary."),
        "stats": ("ai", "COLLECT STATISTICS", "Removed. Snowflake does not need manual statistics. Left as a comment so reviewers can see it was dropped on purpose."),
    },
    tests=[
        ("Row-count parity with legacy snapshot", "parity"),
        ("Latest row per {{key}} kept (QUALIFY)", "behavior"),
        ("Midnight timezone boundary maps to the right date", "edge"),
        ("Insert failure rolls back delete", "error"),
        ("Checksum parity on {{measure}}", "parity"),
    ],
)

TEMPLATES["plsql_cursor"] = dict(
    dialect="Oracle PL/SQL", obj="Stored procedure", level=1, base_cov=0.78,
    name="{{schema}}.load_{{entity}}_daily", path="legacy/oracle/pkg_{{schema_l}}/load_{{entity}}_daily.prc",
    legacy="""CREATE OR REPLACE PROCEDURE {{schema}}.load_{{entity}}_daily IS
  CURSOR c_src IS   --@issue:cursor
    SELECT {{key}}, {{attr}}, {{measure}}, status_cd
      FROM stg_{{entity}}
     WHERE load_dt = TRUNC(SYSDATE);   --@issue:sysdate
  v_bucket VARCHAR2(10);   --@issue:cursor
BEGIN
  FOR r IN c_src LOOP   --@issue:cursor
    v_bucket := DECODE(r.status_cd, 'A', 'ACTIVE',   --@issue:decode
                                    'H', 'HOLD',
                                    'CLOSED');
    INSERT INTO {{schema}}.{{table}} ({{key}}, {{attr}}, {{measure}}, bucket, load_dt)
    VALUES (r.{{key}}, r.{{attr}}, NVL(r.{{measure}}, 0), v_bucket, SYSDATE);   --@issue:nvl,sysdate
  END LOOP;   --@issue:cursor
  COMMIT;   --@issue:commit
EXCEPTION
  WHEN DUP_VAL_ON_INDEX THEN   --@issue:dupval
    ROLLBACK;
    RAISE_APPLICATION_ERROR(-20010, 'duplicate {{entity}} key');   --@issue:dupval
END load_{{entity}}_daily;
/""",
    target="""CREATE OR REPLACE PROCEDURE {{schema}}.load_{{entity}}_daily()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  dup_key EXCEPTION (-20010, 'duplicate {{entity}} key');   --@ai:dupval
BEGIN
  IF (EXISTS (SELECT s.{{key}} FROM stg_{{entity}} s   --@ai:dupval
               LEFT JOIN {{schema}}.{{table}} t ON t.{{key}} = s.{{key}}   --@ai:dupval
              WHERE s.load_dt = CURRENT_DATE()
              GROUP BY s.{{key}}
             HAVING COUNT(*) > 1 OR COUNT(t.{{key}}) > 0)) THEN   --@ai:dupval
    RAISE dup_key;   --@ai:dupval
  END IF;
  INSERT INTO {{schema}}.{{table}} ({{key}}, {{attr}}, {{measure}}, bucket, load_dt)   --@ai:cursor
  SELECT {{key}}, {{attr}}, NVL({{measure}}, 0),   --@det:nvl
         DECODE(status_cd, 'A', 'ACTIVE', 'H', 'HOLD', 'CLOSED'),   --@det:decode
         CURRENT_TIMESTAMP()   --@det:sysdate
    FROM stg_{{entity}}
   WHERE load_dt = CURRENT_DATE();   --@det:sysdate
  RETURN 'OK: ' || SQLROWCOUNT;   --@ai:commit
END;
$$;""",
    notes={
        "cursor": ("ai", "Row-by-row cursor loop", "Devin rewrote the FOR loop as one set-based INSERT ... SELECT. Same output, one statement instead of one round trip per row. A parity test compares it with the legacy output."),
        "sysdate": ("det", "SYSDATE / TRUNC(SYSDATE)", "Rule-based rewrite to CURRENT_TIMESTAMP() and CURRENT_DATE()."),
        "decode": ("det", "DECODE", "Supported natively. Moved into the SELECT list as part of the set-based rewrite."),
        "nvl": ("det", "NVL", "Supported natively. Kept as-is."),
        "commit": ("ai", "Explicit COMMIT", "Dropped. The single INSERT ... SELECT is atomic, so a failure leaves no partial rows."),
        "dupval": ("ai", "DUP_VAL_ON_INDEX handler", "Snowflake does not enforce unique keys, so this exception would never fire and duplicates would slip through. Devin added an explicit check for duplicates in the batch and against keys already in the target. It raises the same error code (-20010) so downstream alerting still matches."),
    },
    tests=[
        ("Parity: set-based output equals cursor output", "parity"),
        ("Bucket mapping A/H/other", "behavior"),
        ("Duplicate key in batch raises -20010", "error"),
        ("Key already in target raises -20010", "error"),
        ("NULL {{measure}} lands as 0", "edge"),
        ("Only today's partition is loaded", "behavior"),
    ],
)

TEMPLATES["td_mart"] = dict(
    dialect="Teradata BTEQ", obj="View", level=2, base_cov=0.88,
    name="mart.v_{{entity}}_monthly", path="legacy/teradata/views/v_{{entity}}_monthly.sql",
    legacy="""REPLACE VIEW mart.v_{{entity}}_monthly AS   --@issue:replace
LOCKING ROW FOR ACCESS   --@issue:locking
SEL TRUNC(event_dt, 'MM') AS month_start,   --@issue:trunc
    {{attr}},
    SUM({{measure}}) (FORMAT 'ZZZ,ZZZ,ZZ9.99') AS total_{{measure}},   --@issue:format
    COUNT(DISTINCT {{key}}) AS active_{{entity}}_cnt,
    ADD_MONTHS(TRUNC(event_dt, 'MM'), 1) - 1 AS month_end   --@issue:datemath
FROM {{schema}}.{{table}}
WHERE event_dt >= ADD_MONTHS(CURRENT_DATE, -24)
GROUP BY 1, 2, 5;""",
    target="""CREATE OR REPLACE VIEW mart.v_{{entity}}_monthly AS   --@det:replace,locking
SELECT DATE_TRUNC('MONTH', event_dt) AS month_start,   --@det:trunc
       {{attr}},
       SUM({{measure}})::NUMBER(14,2) AS total_{{measure}},   --@ai:format
       COUNT(DISTINCT {{key}}) AS active_{{entity}}_cnt,
       LAST_DAY(DATE_TRUNC('MONTH', event_dt)) AS month_end   --@ai:datemath
FROM {{schema}}.{{table}}
WHERE event_dt >= ADD_MONTHS(CURRENT_DATE(), -24)
GROUP BY 1, 2, 5;""",
    notes={
        "replace": ("det", "REPLACE VIEW", "Rule-based rewrite to CREATE OR REPLACE VIEW."),
        "locking": ("det", "LOCKING ROW FOR ACCESS", "Dropped. Snowflake reads never block writers."),
        "trunc": ("det", "TRUNC(date, 'MM')", "Rule-based rewrite to DATE_TRUNC('MONTH', ...)."),
        "format": ("ai", "Display FORMAT on SUM", "The FORMAT phrase changed the type the BI tool saw. Devin cast to NUMBER(14,2) so the dashboard shows the same rounding, and checked the widest seeded month fits."),
        "datemath": ("ai", "Date arithmetic (date - 1)", "Integer arithmetic on dates is replaced with LAST_DAY. A generated test covers February in leap years."),
    },
    tests=[
        ("Monthly totals match legacy (24 months)", "parity"),
        ("Leap-year February month_end", "edge"),
        ("Rounding to 2 decimals matches BI extract", "parity"),
        ("Distinct {{key}} count parity", "parity"),
    ],
)

TEMPLATES["plsql_hier"] = dict(
    dialect="Oracle PL/SQL", obj="View", level=2, base_cov=0.81,
    name="{{schema}}.v_{{entity}}_hierarchy", path="legacy/oracle/views/v_{{entity}}_hierarchy.sql",
    legacy="""CREATE OR REPLACE VIEW {{schema}}.v_{{entity}}_hierarchy AS
SELECT {{key}},
       parent_{{key}},
       LPAD(' ', 2 * (LEVEL - 1)) || {{attr}} AS tree_label,
       LEVEL AS depth,
       SYS_CONNECT_BY_PATH({{attr}}, '/') AS node_path   --@issue:path
  FROM {{schema}}.{{table}}
 WHERE ROWNUM <= 5000   --@issue:rownum
 START WITH parent_{{key}} IS NULL
CONNECT BY NOCYCLE PRIOR {{key}} = parent_{{key}}   --@issue:nocycle
 ORDER SIBLINGS BY {{attr}};   --@issue:siblings""",
    target="""CREATE OR REPLACE VIEW {{schema}}.v_{{entity}}_hierarchy AS
SELECT {{key}},
       parent_{{key}},
       LPAD(' ', 2 * (LEVEL - 1)) || {{attr}} AS tree_label,
       LEVEL AS depth,
       SYS_CONNECT_BY_PATH({{attr}}, '/') AS node_path   --@det:path
  FROM {{schema}}.{{table}}
 START WITH parent_{{key}} IS NULL
CONNECT BY PRIOR {{key}} = parent_{{key}}   --@ai:nocycle
 ORDER BY node_path   --@ai:siblings
 LIMIT 5000;   --@ai:rownum""",
    notes={
        "path": ("det", "CONNECT BY / SYS_CONNECT_BY_PATH", "Supported natively. Kept as-is."),
        "rownum": ("ai", "ROWNUM filter before hierarchy", "In Oracle, ROWNUM is applied before the tree is ordered, so which 5,000 rows came back was effectively random. Devin swapped it for a deterministic LIMIT after ordering and flagged the behavior change for the reviewer."),
        "nocycle": ("ai", "CONNECT BY NOCYCLE", "NOCYCLE is not available. Devin added a data-quality test that fails if the seeded hierarchy contains a cycle, so a bad parent link is caught before the view runs."),
        "siblings": ("ai", "ORDER SIBLINGS BY", "Not supported. Ordering by the materialized path gives the same depth-first, alphabetical-within-parent order."),
    },
    tests=[
        ("Hierarchy has no cycles", "edge"),
        ("Depth-first order matches legacy", "parity"),
        ("Node count parity (root to leaf)", "parity"),
        ("LIMIT returns deterministic rows", "behavior"),
    ],
)

TEMPLATES["tsql_report"] = dict(
    dialect="SQL Server T-SQL", obj="View", level=3, base_cov=0.86,
    name="rpt.vw_{{entity}}_latest", path="legacy/sqlserver/views/vw_{{entity}}_latest.sql",
    legacy="""CREATE VIEW rpt.vw_{{entity}}_latest AS
SELECT TOP 100 PERCENT   --@issue:top
       c.{{key}},
       c.{{attr}},
       l.last_{{measure}},
       DATEDIFF(day, l.last_event_at, GETDATE()) AS days_since,   --@issue:getdate
       CASE WHEN l.last_{{measure}} IS NULL THEN 'n/a'
            ELSE CAST(l.last_{{measure}} AS VARCHAR(20)) END AS display_value
FROM {{schema}}.{{table}} c
CROSS APPLY (   --@issue:apply
    SELECT TOP 1 e.{{measure}} AS last_{{measure}}, e.event_at AS last_event_at   --@issue:apply
    FROM {{schema}}.{{entity}}_events e
    WHERE e.{{key}} = c.{{key}}
    ORDER BY e.event_at DESC   --@issue:apply
) l
ORDER BY c.{{key}};   --@issue:orderby""",
    target="""CREATE OR REPLACE VIEW rpt.vw_{{entity}}_latest AS
SELECT c.{{key}},   --@ai:top
       c.{{attr}},
       l.last_{{measure}},
       DATEDIFF(day, l.last_event_at, CURRENT_TIMESTAMP()) AS days_since,   --@det:getdate
       CASE WHEN l.last_{{measure}} IS NULL THEN 'n/a'
            ELSE CAST(l.last_{{measure}} AS VARCHAR(20)) END AS display_value
FROM {{schema}}.{{table}} c
JOIN (   --@ai:apply
    SELECT e.{{key}}, e.{{measure}} AS last_{{measure}}, e.event_at AS last_event_at   --@ai:apply
    FROM {{schema}}.{{entity}}_events e
    QUALIFY ROW_NUMBER() OVER (PARTITION BY e.{{key}} ORDER BY e.event_at DESC) = 1   --@ai:apply
) l
  ON l.{{key}} = c.{{key}};   --@ai:orderby""",
    notes={
        "top": ("ai", "TOP 100 PERCENT in a view", "A SQL Server trick to allow ORDER BY in a view. It does not guarantee order and has no equivalent, so it is removed."),
        "getdate": ("det", "GETDATE()", "Rule-based rewrite to CURRENT_TIMESTAMP()."),
        "apply": ("ai", "CROSS APPLY (SELECT TOP 1 ...)", "Rewritten as an inner join to a QUALIFY ROW_NUMBER() subquery. Like CROSS APPLY, it drops rows with no events. A test checks this."),
        "orderby": ("ai", "ORDER BY inside a view", "Dropped. Consumers sort explicitly. Devin checked the two seeded BI extracts that read this view, and both already have ORDER BY."),
    },
    tests=[
        ("Latest event per {{key}} matches legacy", "parity"),
        ("Rows with no events are excluded", "behavior"),
        ("days_since is non-negative", "edge"),
        ("display_value 'n/a' for NULL", "edge"),
    ],
)

# ---------------------------------------------------------------- estate layout
PLAN = []  # (template, entity_idx)
for i, e in enumerate(ENTITIES):
    PLAN.append(("bteq_load" if i % 2 == 0 else "tsql_upsert", i))
for i in [0, 2, 4, 6, 8, 10, 11]:
    PLAN.append(("plsql_cursor", i))
for i in [0, 3, 4, 9]:
    PLAN.append(("td_mart", i))
for i in [5, 7]:
    PLAN.append(("plsql_hier", i))
for i in [1, 2, 6, 8]:
    PLAN.append(("tsql_report", i))


def fill(text, ctx):
    return re.sub(r"\{\{(\w+)\}\}", lambda m: ctx[m.group(1)], text)


MARK = re.compile(r"\s+--@(issue|det|ai):([\w,]+)\s*$")


def parse(text):
    lines, marks = [], []
    for raw in text.split("\n"):
        m = MARK.search(raw)
        if m:
            lines.append(raw[: m.start()].rstrip())
            marks.append(m.group(2).split(","))
        else:
            lines.append(raw.rstrip())
            marks.append([])
    return lines, marks


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


modules = []
for n, (tkey, ei) in enumerate(PLAN, start=1):
    t = TEMPLATES[tkey]
    domain, entity, key, attr, measure, table = ENTITIES[ei]
    ctx = dict(schema=domain, schema_l=domain.lower(), entity=entity, key=key, attr=attr, measure=measure, table=table)
    legacy_lines, legacy_marks = parse(fill(t["legacy"], ctx))
    target_lines, target_marks = parse(fill(t["target"], ctx))
    notes = []
    for k, (kind, title, text) in t["notes"].items():
        notes.append(dict(key=k, kind=kind, title=title, text=fill(text, ctx)))
    ai_keys = [x["key"] for x in notes if x["kind"] == "ai"]

    loc = int(rng.triangular(380, 5200, 1100) * (1.25 if t["level"] == 1 else 1))
    loc = int(round(loc, -1))
    coverage = round(clamp(t["base_cov"] + rng.uniform(-0.07, 0.06), 0.62, 0.97), 3)
    occurrences = max(len(ai_keys), int(len(ai_keys) * loc / 700 * rng.uniform(0.6, 1.3)))
    legacy_test_cov = round(rng.choice([0, 0, 0.05, 0.1, 0.18, 0.25, 0.35, 0.5]), 2)
    tests = []
    for name, cat in t["tests"]:
        tests.append(dict(name=fill(name, ctx), category=cat, ms=rng.randint(180, 4200),
                          assertions=rng.randint(3, 40)))
    flaky = rng.random() < 0.45
    modules.append(dict(
        id="M-%03d" % n, template=tkey, name=fill(t["name"], ctx), path=fill(t["path"], ctx),
        dialect=t["dialect"], object_type=t["obj"], domain=domain, entity=entity, level=t["level"],
        team=TEAMS[domain], loc=loc, last_modified=rng.randint(2009, 2021),
        runs_per_day=rng.choice([1, 1, 1, 4, 24, 96]), criticality=None,
        det_coverage=coverage, ai_fixes=occurrences, legacy_test_coverage=legacy_test_cov,
        constructs=[x["title"] for x in notes],
        legacy=dict(lines=legacy_lines, marks=legacy_marks),
        target=dict(lines=target_lines, marks=target_marks),
        notes=notes, tests=tests,
        first_run_failure=(rng.choice(tests)["name"] if flaky else None),
        deps=[],
    ))

# dependencies: level 1 <- level 0 same entity (+ maybe 1 other in domain); level 2 <- 1/0 same entity
by_level = {}
for m in modules:
    by_level.setdefault(m["level"], []).append(m)


def find(level, entity=None, domain=None):
    return [m for m in by_level.get(level, []) if (entity is None or m["entity"] == entity) and (domain is None or m["domain"] == domain)]


for m in modules:
    if m["level"] == 1:
        m["deps"] = [x["id"] for x in find(0, entity=m["entity"])]
        sib = [x for x in find(0, domain=m["domain"]) if x["entity"] != m["entity"]]
        if sib and rng.random() < 0.5:
            m["deps"].append(sib[0]["id"])
    elif m["level"] == 2:
        src = find(1, entity=m["entity"]) or find(0, entity=m["entity"])
        m["deps"] = [x["id"] for x in src]
    elif m["level"] == 3:
        own = find(1, entity=m["entity"]) or find(0, entity=m["entity"])
        marts = rng.sample(by_level[2], 2)
        m["deps"] = [x["id"] for x in own] + [x["id"] for x in marts]

for m in modules:
    m["dependents"] = [x["id"] for x in modules if m["id"] in x["deps"]]

# criticality tiers and risk scores
for m in modules:
    m["criticality"] = 1 if (m["domain"] in ("FINANCE", "SALES") or m["runs_per_day"] >= 24) else (2 if m["level"] < 3 else 3)

max_loc = max(m["loc"] for m in modules)
for m in modules:
    ai_notes = sum(1 for x in m["notes"] if x["kind"] == "ai")
    factors = [
        ("Size", 0.20, clamp(m["loc"] / max_loc)),
        ("Constructs needing AI remediation", 0.25, clamp(ai_notes / 6)),
        ("Deterministic coverage gap", 0.20, clamp((1 - m["det_coverage"]) / 0.35)),
        ("Downstream dependents", 0.15, clamp(len(m["dependents"]) / 3)),
        ("Missing legacy tests", 0.10, 1 - m["legacy_test_coverage"]),
        ("Business criticality", 0.10, {1: 1.0, 2: 0.55, 3: 0.2}[m["criticality"]]),
    ]
    m["risk_factors"] = [dict(name=n_, weight=w, value=round(v, 3), points=round(w * v * 100, 1)) for n_, w, v in factors]
    m["raw_risk"] = sum(f["points"] for f in m["risk_factors"])

# spread raw scores onto a 12-92 scale; factor points are scaled with them so they still add up
lo, hi = min(m["raw_risk"] for m in modules), max(m["raw_risk"] for m in modules)
for m in modules:
    target = 12 + (m["raw_risk"] - lo) / (hi - lo) * 80
    k = target / m["raw_risk"]
    for f in m["risk_factors"]:
        f["points"] = round(f["points"] * k, 1)
    m["risk"] = int(round(sum(f["points"] for f in m["risk_factors"])))
    del m["raw_risk"]

company = dict(
    name="Granite Peak Outfitters (fictional)",
    estate="GPO Enterprise Data Warehouse",
    source_platforms=["Teradata 16.20", "SQL Server 2016", "Oracle 12c"],
    target="Snowflake (Snowflake Scripting SQL)",
    sim_start="2026-11-02T09:00:00",
)

out = dict(
    generated_by="scripts/seed.py", seed=SEED, company=company, reviewers=REVIEWERS,
    modules=modules,
)
os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
with open(os.path.join(ROOT, "data", "seed.json"), "w") as f:
    json.dump(out, f, indent=1)
with open(os.path.join(ROOT, "data", "seed.js"), "w") as f:
    f.write("// Generated by scripts/seed.py. Synthetic data only. Do not edit by hand.\n")
    f.write("window.SEED = " + json.dumps(out, separators=(",", ":")) + ";\n")

print("modules:", len(modules), "total LOC:", sum(m["loc"] for m in modules))
for m in sorted(modules, key=lambda x: -x["risk"])[:8]:
    print(m["id"], m["risk"], m["name"], m["dialect"], m["deps"], m["dependents"])
