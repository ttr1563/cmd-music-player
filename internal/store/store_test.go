package store

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	s, err := New(filepath.Join(t.TempDir(), "data"))
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func TestPythonVaultV1Compatibility(t *testing.T) {
	// Produced independently by Python cryptography's Scrypt/AESGCM.
	fixture := `{"version":1,"salt":"AAECAwQFBgcICQoLDA0ODw==","nonce":"AAECAwQFBgcICQoL","data":"KpEWS61BpCjnGV2lsZITZkQdyuGq/qSvF/ArHKHuP+f5p2pRm93YAOMXD8xzosiCRgfU5SqMBQcRavSbAV7fYcHUvoILE52yddUnTA=="}`
	s := testStore(t)
	if err := s.SaveConfig(DefaultConfig()); err != nil {
		t.Fatal(err)
	}
	if err := s.write("vault.enc", []byte(fixture)); err != nil {
		t.Fatal(err)
	}
	accounts, err := s.Vault("test-passphrase-123")
	if err != nil {
		t.Fatal(err)
	}
	if accounts["personal"]["cookie"] != "fixture-only" || accounts["personal"]["x-goog-authuser"] != "1" {
		t.Fatal("account was not preserved")
	}
	if err = s.SaveVault(accounts, "test-passphrase-123"); err != nil {
		t.Fatal(err)
	}
	other, _ := New(s.Dir)
	roundtrip, err := other.Vault("test-passphrase-123")
	if err != nil || roundtrip["personal"]["cookie"] != "fixture-only" {
		t.Fatal("roundtrip failed", err)
	}
	if _, err = other.Vault("wrong"); err == nil {
		t.Fatal("wrong phrase accepted")
	}
}
func TestVaultRejectsConcurrentUpdate(t *testing.T) {
	s := testStore(t)
	other, _ := New(s.Dir)
	accounts := Accounts{"one": {"cookie": "synthetic"}}
	if err := s.SaveVault(accounts, "fixture-only"); err != nil {
		t.Fatal(err)
	}
	if err := other.SaveVault(accounts, "fixture-only"); err == nil {
		t.Fatal("stale update accepted")
	}
}
func TestVaultRejectsUnknownVersionWithoutWriting(t *testing.T) {
	s := testStore(t)
	s.ensure()
	original := []byte(`{"version":2}`)
	s.write("vault.enc", original)
	if _, err := s.Vault("anything"); err == nil {
		t.Fatal("unknown version accepted")
	}
	b, _ := os.ReadFile(filepath.Join(s.Dir, "vault.enc"))
	if string(b) != string(original) {
		t.Fatal("vault changed")
	}
}
func TestConfigValidationAndNoWrite(t *testing.T) {
	for _, body := range []string{`{"version":2,"service":"youtube-music","account":null,"volume":70}`, `{"version":1,"service":"youtube-music","account":null,"volume":101}`, `{"version":1,"service":"youtube-music","account":null}`, `{"version":null,"service":"youtube-music","account":null,"volume":0}`, `{"version":1,"service":"youtube-music","account":"../bad","volume":0}`} {
		t.Run(body, func(t *testing.T) {
			s := testStore(t)
			s.ensure()
			s.write("config.json", []byte(body))
			if _, err := s.Config(); err == nil {
				t.Fatal("invalid config accepted")
			}
			b, _ := os.ReadFile(filepath.Join(s.Dir, "config.json"))
			if string(b) != body {
				t.Fatal("config changed")
			}
		})
	}
}
func TestPurgePreservesUnknownFiles(t *testing.T) {
	s := testStore(t)
	s.SaveConfig(DefaultConfig())
	p := filepath.Join(s.Dir, "user-note")
	os.WriteFile(p, []byte("keep"), 0600)
	if err := s.Purge(); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(p)
	if err != nil || string(b) != "keep" {
		t.Fatal("unrelated file removed")
	}
	if _, err = os.Stat(filepath.Join(s.Dir, ".music-cli")); err != nil {
		t.Fatal("marker removed")
	}
}
func TestPurgeRemovesOwnedDirectory(t *testing.T) {
	s := testStore(t)
	s.SaveConfig(DefaultConfig())
	if err := s.Purge(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(s.Dir); !os.IsNotExist(err) {
		t.Fatal("owned directory remains")
	}
}
func TestUnmarkedDirectoryRejected(t *testing.T) {
	if _, err := New(t.TempDir()); err == nil {
		t.Fatal("unowned directory accepted")
	}
}
func TestDataSymlinkRejected(t *testing.T) {
	s := testStore(t)
	s.SaveConfig(DefaultConfig())
	outside := filepath.Join(t.TempDir(), "unrelated")
	os.WriteFile(outside, []byte("keep"), 0600)
	p := filepath.Join(s.Dir, "vault.enc")
	if err := os.Symlink(outside, p); err != nil {
		t.Skip("symlink unavailable")
	}
	if err := s.Purge(); err == nil {
		t.Fatal("symlink accepted")
	}
	b, _ := os.ReadFile(outside)
	if string(b) != "keep" {
		t.Fatal("symlink target changed")
	}
}

func TestEmptyVaultIsCorruptAndPreserved(t *testing.T) {
	s := testStore(t)
	s.ensure()
	s.write("vault.enc", []byte{})
	if _, err := s.Vault("phrase"); err == nil {
		t.Fatal("empty vault treated as missing")
	}
	if err := s.SaveVault(Accounts{}, "phrase"); err == nil {
		t.Fatal("corrupt vault overwritten")
	}
}

func TestVaultTamperingAndNoPlaintext(t *testing.T) {
	s := testStore(t)
	if err := s.SaveVault(Accounts{"personal": {"cookie": "private-synthetic-token"}}, "test-passphrase"); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(s.Dir, "vault.enc")
	b, _ := os.ReadFile(p)
	if strings.Contains(string(b), "private-synthetic-token") {
		t.Fatal("plaintext credential persisted")
	}
	var e envelope
	json.Unmarshal(b, &e)
	first := "A"
	if e.Data[0] == 'A' {
		first = "B"
	}
	e.Data = first + e.Data[1:]
	modified, _ := json.Marshal(e)
	s.write("vault.enc", modified)
	if _, err := s.Vault("test-passphrase"); err == nil {
		t.Fatal("tampering accepted")
	}
}
func TestReadOnlyDoesNotCreateData(t *testing.T) {
	s := testStore(t)
	if _, err := s.Config(); err != nil {
		t.Fatal(err)
	}
	if s.HasVault() {
		t.Fatal("unexpected vault")
	}
	if _, err := os.Stat(s.Dir); !os.IsNotExist(err) {
		t.Fatal("read created directory")
	}
}
