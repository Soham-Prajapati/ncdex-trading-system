# Project decisions

## 2026-10-06 — Use Neon Postgres as the operational and analytics source

Neon was provisioned in `aws-ap-southeast-1` because it is the requested database and is the closest supported region to India. The app will use the pooled URL; migrations and Power BI use the direct URL.

## 2026-10-06 — Keep Kafka out of the first implementation

The supplied final direction removes Kafka from the required flow. The first release uses Postgres transactions and an events table; event streaming can be added later without changing the core schema contract.

