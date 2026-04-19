package contracts

import (
	"errors"

	"github.com/John-Halo117/ARK/arkfield/internal/models"
)

func ValidateEvent(e models.Event) error {
	if e.CID == "" {
		return errors.New("missing cid")
	}
	if e.StateHash == "" {
		return errors.New("missing state_hash")
	}
	if e.Sequence == 0 {
		return errors.New("invalid sequence")
	}
	return nil
}
