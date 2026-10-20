package main

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestDecoderLicenseGate(t *testing.T) {
	for _, test := range []struct {
		name, text string
		accepted   bool
	}{{"LGPL2.1 line wrapping", "GNU Lesser General Public\nLicense ... version 2.1", true}, {"LGPL2.1 single line", "GNU Lesser General Public License ... version 2.1", true}, {"GPL", "GNU General Public License ... version 2", false}, {"LGPL3", "GNU Lesser General Public License ... version 3", false}, {"nonfree", "not legally redistributable", false}, {"empty", "", false}} {
		t.Run(test.name, func(t *testing.T) {
			if accepted := verifyLicense([]byte(test.text)) == nil; accepted != test.accepted {
				t.Fatal("incorrect license decision")
			}
		})
	}
}

func TestRequiredPCMOutputCannotBeDisabled(t *testing.T) {
	enabled := []byte("#define CONFIG_AAC_DECODER 1\n#define CONFIG_OPUS_DECODER 1\n#define CONFIG_PCM_F32LE_ENCODER 1\n#define CONFIG_PCM_F32LE_MUXER 1\n")
	if err := verifyComponents(enabled); err != nil {
		t.Fatal(err)
	}
	disabled := []byte("#define CONFIG_AAC_DECODER 1\n#define CONFIG_OPUS_DECODER 1\n#define CONFIG_PCM_F32LE_ENCODER 1\n#define CONFIG_PCM_F32LE_MUXER 0\n")
	if verifyComponents(disabled) == nil {
		t.Fatal("bundle without PCM output accepted")
	}
}

func TestPortableZIPRoundTrip(t *testing.T) {
	base := t.TempDir()
	source := filepath.Join(base, "fest")
	if err := os.MkdirAll(filepath.Join(source, "runtime"), 0755); err != nil {
		t.Fatal(err)
	}
	data := []byte{0, 1, 2, 255, 10}
	if err := os.WriteFile(filepath.Join(source, "runtime", "decoder.dll"), data, 0644); err != nil {
		t.Fatal(err)
	}
	bundle := filepath.Join(base, "bundle.zip")
	if err := archive(source, bundle); err != nil {
		t.Fatal(err)
	}
	destination := t.TempDir()
	if err := extractZIP(bundle, destination); err != nil {
		t.Fatal(err)
	}
	actual, err := os.ReadFile(filepath.Join(destination, "fest", "runtime", "decoder.dll"))
	if err != nil || !bytes.Equal(actual, data) {
		t.Fatal("ZIP extraction changed bundle bytes", err)
	}
	if extractZIP(bundle, destination) == nil {
		t.Fatal("existing bundle overwritten")
	}
}

func TestZIPCannotEscapeDestination(t *testing.T) {
	base := t.TempDir()
	bundle := filepath.Join(base, "bad.zip")
	f, err := os.Create(bundle)
	if err != nil {
		t.Fatal(err)
	}
	z := zip.NewWriter(f)
	w, err := z.Create("../outside")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = w.Write([]byte("unexpected")); err != nil {
		t.Fatal(err)
	}
	if err = z.Close(); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(base, "destination")
	if err = os.Mkdir(destination, 0755); err != nil {
		t.Fatal(err)
	}
	if extractZIP(bundle, destination) == nil {
		t.Fatal("ZIP traversal accepted")
	}
	if _, err = os.Stat(filepath.Join(base, "outside")); !os.IsNotExist(err) {
		t.Fatal("file escaped destination")
	}
}
