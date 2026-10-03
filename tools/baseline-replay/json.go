package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
)

type object = map[string]any
type invalidEvidence struct{ message string }

func require(ok bool, format string, args ...any) {
	if !ok {
		panic(invalidEvidence{fmt.Sprintf(format, args...)})
	}
}

func digest(raw []byte) string { return fmt.Sprintf("%x", sha256.Sum256(raw)) }

func fileDigest(name string) string {
	f, err := os.Open(name)
	require(err == nil, "hash %s: %v", name, err)
	defer f.Close()
	hash := sha256.New()
	_, err = io.Copy(hash, f)
	require(err == nil, "hash %s: %v", name, err)
	return fmt.Sprintf("%x", hash.Sum(nil))
}

func validatorSources(root string) object {
	files := object{}
	for _, name := range []string{"go.mod", "json.go", "freeze.go", "receipts.go", "native.go", "process_unix.go", "main.go", "replay_test.go", "revision2.go", "reference.go", "revision2_test.go"} {
		relative := "tools/baseline-replay/" + name
		files[relative] = digest(readBytes(filepath.Join(root, relative)))
	}
	return files
}

func readBytes(name string) []byte {
	info, err := os.Lstat(name)
	require(err == nil, "read %s: %v", name, err)
	require(info.Mode().IsRegular() && info.Size() <= 32<<20, "nonregular or oversized evidence: %s", name)
	raw, err := os.ReadFile(name)
	require(err == nil, "read %s: %v", name, err)
	return raw
}

func decode(raw []byte) any {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var value any
	require(dec.Decode(&value) == nil, "invalid JSON")
	var extra any
	require(dec.Decode(&extra) == io.EOF, "extra JSON value")
	return value
}

func doc(name string) object { return obj(decode(readBytes(name))) }
func obj(value any) object {
	v, ok := value.(map[string]any)
	require(ok, "expected JSON object")
	return v
}
func rows(value any) []any {
	if value == nil {
		return nil
	}
	v, ok := value.([]any)
	require(ok, "expected JSON array")
	return v
}
func at(value any, keys ...string) any {
	for _, key := range keys {
		if value == nil {
			return nil
		}
		value = obj(value)[key]
	}
	return value
}
func str(value any) string {
	if value == nil {
		return ""
	}
	v, ok := value.(string)
	require(ok, "expected string")
	return v
}
func num(value any) int64 {
	if value == nil {
		return 0
	}
	v, ok := value.(json.Number)
	require(ok, "expected JSON integer")
	n, err := strconv.ParseInt(string(v), 10, 64)
	require(err == nil, "invalid int64 %q", v)
	return n
}
func requiredNum(value any) int64 {
	require(value != nil, "missing required integer observation")
	return num(value)
}
func eq(a, b any) bool { return reflect.DeepEqual(a, b) }
func index(value any, key string) map[string]object {
	result := map[string]object{}
	for _, row := range rows(value) {
		o := obj(row)
		id := str(o[key])
		_, duplicate := result[id]
		require(id != "" && !duplicate, "missing or duplicate %s: %s", key, id)
		result[id] = o
	}
	return result
}
func sameKeys(a, b map[string]object) bool {
	if len(a) != len(b) {
		return false
	}
	for key := range a {
		if _, ok := b[key]; !ok {
			return false
		}
	}
	return true
}
func local(root, relative string) string {
	require(filepath.IsLocal(relative), "nonlocal evidence path %q", relative)
	return filepath.Join(root, relative)
}
func putJSON(name string, value any) {
	raw, err := json.MarshalIndent(value, "", "  ")
	require(err == nil, "encode %s: %v", name, err)
	require(os.WriteFile(name, append(raw, '\n'), 0644) == nil, "write %s", name)
}
func marshalJSON(value any) []byte {
	raw, err := json.Marshal(value)
	require(err == nil, "encode JSON: %v", err)
	return raw
}
