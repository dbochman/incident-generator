# Kubernetes Pending Pod Scenario Seed

Seed data is currently represented by the pending-pod fixture. The live harness
seed should create the `analytics` namespace and a `report-generator` pod with
oversized CPU requests so scheduler events include `Insufficient cpu`.
