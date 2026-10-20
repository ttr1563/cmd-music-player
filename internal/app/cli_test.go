package app

import (
	"os"
	"path/filepath"
	"testing"
)

func TestConfigCommandsAndPurge(t *testing.T) {
	root := filepath.Join(t.TempDir(), "data")
	for _, args := range [][]string{{"config", "set", "volume", "0"}, {"config", "show"}, {"config", "path"}, {"purge", "--yes"}} {
		if err := Run(append([]string{"--data-dir", root}, args...)); err != nil {
			t.Fatal(args, err)
		}
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("purge did not remove data")
	}
}
func TestCLIRejectsInvalidCommandsWithoutCreatingData(t *testing.T) {
	root := filepath.Join(t.TempDir(), "data")
	for _, args := range [][]string{{"config", "set", "volume", "101"}, {"config", "set", "service", "spotify"}, {"unexpected"}, {"login"}, {"logout"}, {"purge", "--anything"}} {
		if err := Run(append([]string{"--data-dir", root}, args...)); err == nil {
			t.Fatal("invalid command accepted", args)
		}
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("invalid command wrote data")
	}
}
