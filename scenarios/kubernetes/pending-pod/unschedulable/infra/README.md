# Kubernetes Pending Pod Scenario Infra

The fixture-backed path uses recorded `kubectl get pod` and `kubectl describe pod`
outputs from `evals/pending-fixtures/kubernetes-pending-insufficient-cpu`.

The live Phase A path targets the `kind` harness archetype and should seed a
namespace with a pod whose CPU request exceeds available node allocatable CPU.
