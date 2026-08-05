"""Check Windows speech synthesis used by the voice reminders."""

import base64
import subprocess

from voice import list_voices, speak_script


def main() -> None:
    voices = list_voices()
    print("voices:", [f"{v.description}|{v.language}" for v in voices])
    if not voices:
        raise SystemExit("no SAPI voices found")
    voice_name = voices[0].description
    script = speak_script("语音提醒测试，请注意，还有五分钟到期。", voice_name=voice_name)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=60,
    )
    print("returncode:", result.returncode)
    if result.returncode != 0:
        print("stderr:", result.stderr.decode("utf-8", errors="replace").strip())
        raise SystemExit("speech synthesis check failed")


if __name__ == "__main__":
    main()
