package main

import "testing"

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
