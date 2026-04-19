package ingestion

import (
	"context"
	"crypto/sha256"
	"crypto/sha3"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/budget"
	"github.com/John-Halo117/ARK/arkfield/internal/contracts"
	"github.com/John-Halo117/ARK/arkfield/internal/models"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

const (
	stateHashKeyPrefix = "ark:statehash:"
	sequenceKey        = "ark:events:sequence"
	subjectName        = "ark.events.cid"
)

type Service struct {
	Redis  *transport.RedisClient
	NATS   *transport.NATSClient
	Kernel *stability.Kernel
	Budget *budget.Controller
}

// (rest unchanged until event creation)

	decision := s.Kernel.Evaluate(defaultObservation())
	if decision.Freeze {
		return nil, false, fmt.Errorf("stability freeze: %s", decision.Reason)
	}

	event := models.Event{CID: cid, Sequence: seq, StateHash: stateHash, ParentCID: req.ParentCID, Repo: repoPath, CommitSHA: req.CommitSHA, Author: meta.Author, OccurredAt: mustParseTime(meta.Date), Canonical: canonicalRaw, Attributes: req.Attributes, StabilityOK: true}

	// NEW: contract validation
	if err := contracts.ValidateEvent(event); err != nil {
		return nil, false, err
	}

	// NEW: budget gating
	if s.Budget != nil && !s.Budget.AllowQueue(int(seq)) {
		return nil, false, errors.New("queue budget exceeded")
	}

	data, err := json.Marshal(event)
