package budget

import "github.com/John-Halo117/ARK/arkfield/internal/config"

type Controller struct {
	cpuLimit       int
	memoryLimitMB  int
	queueDepth     int
	repairAttempts int
	externalCalls  int
}

func NewFromManifest(m config.Manifest) *Controller {
	return &Controller{
		cpuLimit:       m.Budgets.CPU,
		memoryLimitMB:  m.Budgets.MemoryMB,
		queueDepth:     m.Budgets.QueueDepth,
		repairAttempts: m.Budgets.RepairAttempts,
		externalCalls:  m.Budgets.ExternalCalls,
	}
}

func (c *Controller) AllowCPU(v int) bool { return c == nil || v <= c.cpuLimit }
func (c *Controller) AllowMemory(v int) bool { return c == nil || v <= c.memoryLimitMB }
func (c *Controller) AllowQueue(v int) bool { return c == nil || v <= c.queueDepth }
func (c *Controller) AllowRepairAttempts(v int) bool { return c == nil || v <= c.repairAttempts }
func (c *Controller) AllowExternalCalls(v int) bool { return c == nil || v <= c.externalCalls }
