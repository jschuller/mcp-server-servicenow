# CSDM 5 stages and conformance scores

The Common Service Data Model (CSDM) is ServiceNow's reference model for the service-related data in the CMDB. Version 5 is current. This reference is a summary in our own words.

## Domains in CSDM 5

- Foundation
- Ideation & Strategy
- Design & Planning
- Build & Integration
- Service Delivery
- Service Consumption
- Manage Portfolio, which spans the others

Two renames from earlier versions matter when you read class names and relationships:
- **Application services are now Service Instances.** The class is `cmdb_ci_service_auto` and its subclasses.
- **A business application now relates to its services with Uses::Used By.** Earlier versions used Consumes::Consumed By.

## Adoption stages

Instances adopt CSDM in five stages. Each stage builds on the one before.

| Stage | `csdm_stage` value | Typical data |
|-------|--------------------|--------------|
| Foundation | 5 | Locations, companies and business units, product models with owners, CI status values |
| Crawl | 1 | Business applications related to the services that run them |
| Walk | 2 | Technical services and their offerings, with support and change groups |
| Run | 3 | Business services and offerings, related to the services that deliver them |
| Fly | 4 | Information objects and their business applications |

The numeric values were read from a Brazil instance's choice list. Treat the label, not the number, as what you report.

## The scores table: `sn_getwell_csdm_score`

Each row is one conformance metric.

| Field | Meaning |
|-------|---------|
| `name` | What the metric checks, e.g. "Locations with Parents" |
| `csdm_stage` | The stage it belongs to (see above) |
| `result` | A percentage; 100 means the data is complete for this metric |
| `count` | How many records the metric looked at |
| `priority` | 1 is the most important |
| `active` | Whether the metric is in use |

More about the table:
- **Where the scores come from:** a daily scheduled job, "CSDM Get Well Metric Collection", fills the table. Until it has run once, the table and the dashboard are empty.
- **When a score is 0:** a metric whose query hits its aggregate limit scores 0. A metric that runs too long is switched off, which shows as `active=false`.
- **The CMDB equivalent:** `sn_getwell_cmdb_score`, which often needs a CMDB role to read.
- **Who can read it:** `itil` + `snc_read_only` read `sn_getwell_csdm_score` on a Brazil instance; `snc_read_only` alone gets 403.

## Sources
- [CSDM data domains](https://www.servicenow.com/docs/r/brazil/servicenow-platform/common-service-data-model-csdm/csdm-conceptual-model.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/common-service-data-model-csdm/csdm-conceptual-model.md)
- [Configure the CSDM Data Foundations dashboard](https://www.servicenow.com/docs/r/brazil/servicenow-platform/common-service-data-model-csdm/csdm-foundations-dashboard.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/common-service-data-model-csdm/csdm-foundations-dashboard.md)
- [Monitor health in CSDM and CMDB Data Foundations Dashboards](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/csdm-cmdb-foundations-dashboards.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/configuration-management-database-cmdb/csdm-cmdb-foundations-dashboards.md)
