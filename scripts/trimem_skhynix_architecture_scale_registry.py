"""Pin public image metadata for the selected scale tasks, without reselection."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import urllib.error


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def retain(path, value):
    raw = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Registry evidence is immutable")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def screen(instance_ids, *, old_index_reference, output_root, selection_reference):
    if len(instance_ids) != len(set(instance_ids)) or len(instance_ids) != 800:
        raise ValueError("Scale registry requires exact240training+60development+500final unique IDs")
    if reference(old_index_reference["path"]) != old_index_reference or reference(selection_reference["path"]) != selection_reference:
        raise ValueError("Frozen selection or original registry changed")
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    old = json.loads(Path(old_index_reference["path"]).read_bytes())
    existing = {row["instance_id"]: row for row in old["rows"]}
    retain(root / "selection-binding.json", {"instance_ids": sorted(instance_ids),
        "selection_reference": selection_reference, "original_index_reference": old_index_reference,
        "selection_uses_image_availability": False})

    def fetch(identity):
        if identity in existing and existing[identity]["status"] == "AVAILABLE":
            row = existing[identity]
            return {**row, "adopted_index_reference": old_index_reference}
        path = root / "responses" / (identity + ".json")
        name = "swebench/sweb.eval.x86_64." + identity.lower().replace("__", "_1776_")
        url = "https://hub.docker.com/v2/repositories/" + name + "/tags/latest"
        attempts = []
        for number in range(1, 5):
            try:
                if path.exists():
                    raw = path.read_bytes()
                else:
                    request = urllib.request.Request(url, headers={"User-Agent": "SKhynix-public-scale-preflight/1.0"})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ValueError("Registry metadata exceeds byte cap")
                    path.parent.mkdir(exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(raw)
                value = json.loads(raw)
                digest = value["digest"]
                if (not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71
                        or not any(row.get("os") == "linux" and row.get("architecture") == "amd64" for row in value["images"])):
                    raise ValueError("Pinned image lacks linux/amd64 metadata")
                return {"instance_id": identity, "url": url, "status": "AVAILABLE", "image": name + "@" + digest,
                    "harness_image_tag": name + ":latest", "registry_response_reference": reference(path),
                    "registry_response_sha256": hashlib.sha256(raw).hexdigest(),
                    "registry_response_canonical_sha256": hashlib.sha256(canonical(value)).hexdigest()}
            except urllib.error.HTTPError as exc:
                attempts.append({"attempt": number, "http_status": exc.code})
                if exc.code == 404:
                    break
            except Exception as exc:
                attempts.append({"attempt": number, "error_type": type(exc).__name__})
            if number < 4:
                time.sleep(min(20, 5 * number))
        return {"instance_id": identity, "url": url, "status": "UNAVAILABLE_OR_ERROR", "attempts": attempts}

    rows = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(fetch, identity) for identity in instance_ids]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows) % 50 == 0:
                print(json.dumps({"screened": len(rows), "planned": 800,
                    "available": sum(row["status"] == "AVAILABLE" for row in rows)}), flush=True)
    value = {"schema": "skhynix/architecture-public-scale-image-screening/1.0", "rows": sorted(rows, key=lambda row: row["instance_id"]),
        "selection_reference": selection_reference, "original_index_reference": old_index_reference,
        "selected_count": 800, "model_calls": 0, "official_grader_runs": 0,
        "unavailable_ids_reselected": False}
    result = retain(root / "index.json", value)
    print(json.dumps({"reference": result, "available": sum(row["status"] == "AVAILABLE" for row in rows),
        "unavailable": [row["instance_id"] for row in rows if row["status"] != "AVAILABLE"]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--old-index", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    selection = json.loads(Path(args.selection).read_bytes())
    screen(selection["instance_ids"], old_index_reference=reference(args.old_index),
        output_root=args.output_root, selection_reference=reference(args.selection))
