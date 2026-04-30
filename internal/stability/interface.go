package stability

// KernelV42 defines the canonical ARK stability kernel interface
// All systems (NetWatch, JetStream ingestion) MUST call this only.

type KernelV42 interface {
	Evaluate(obs Observation) Decision
}
