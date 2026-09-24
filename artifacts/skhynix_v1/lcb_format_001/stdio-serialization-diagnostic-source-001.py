"""Synthetic stdio serialization only: no model/CLI, real requests or disk writes."""
import hashlib
import json
import subprocess
import sys


CHILD = r'''
import io,json,sys
mode=sys.argv[1]
stream=io.BytesIO()
report={'mode':mode,'stdin_encoding':sys.stdin.encoding,'stdin_errors':sys.stdin.errors}
try:
    # Match the text-stdin route in the frozen broker, or its buffer comparator.
    line=next(iter(sys.stdin if mode=='text' else sys.stdin.buffer))
    value=json.loads(line)
    report['json_parse_succeeded']=True
    report['surrogate_codepoint_count']=sum(0xD800<=ord(c)<=0xDFFF for c in value['synthetic'])
    # Like atomic(): canonicalization happens before write, leaving zero bytes
    # if UTF-8 encoding of a surrogateescaped string raises.
    stream.write(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n')
    report['serialization_exception_class']=None
except Exception as exc:
    report['serialization_exception_class']=type(exc).__name__
report['bytes_written']=len(stream.getvalue())
print(json.dumps(report,ensure_ascii=True))
'''


def reproduce():
    value = {'synthetic': 'SYNTHETIC_' + chr(0xAC00)}
    outputs = []
    for label, mode, escape in (('UTF8_TEXT_STDIN', 'text', False),
                                ('ASCII_ESCAPED_TEXT_STDIN', 'text', True),
                                ('UTF8_BUFFER_STDIN', 'buffer', False)):
        wire = (json.dumps(value, ensure_ascii=escape) + '\n').encode('utf8')
        process = subprocess.run([sys.executable, '-B', '-c', CHILD, mode],
                                 input=wire, capture_output=True, timeout=15)
        if process.returncode:
            raise RuntimeError('SYNTHETIC_CHILD_FAILED')
        output = json.loads(process.stdout)
        output['case'] = label
        output['wire_sha256'] = hashlib.sha256(wire).hexdigest()
        output['wire_bytes'] = len(wire)
        outputs.append(output)
    return {'schema': 'lcb-format-synthetic-stdio-diagnostic/1', 'cases': outputs,
            'synthetic_child_processes': 3, 'native_cli_calls': 0, 'model_calls': 0,
            'grader_calls': 0, 'actual_trial_payloads_read': False,
            'disk_archive_writes': 0,
            'scope': 'Current interpreter/environment reproduction; original broker exception and environment were not recorded.'}


if __name__ == '__main__':
    print(json.dumps(reproduce(), sort_keys=True))
