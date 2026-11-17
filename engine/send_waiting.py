"""Sends the oldest waiting engine job to Kaggle (used by "3c - Send the waiting AI job" at 11:00 am IST).

Waiting jobs are engine/state/waiting.json (the weekly videos) and engine/state/waiting-<run>.json (landmark cases,
or any job that arrived while another run was still on Kaggle). Only one is sent at a time, and nothing is sent while
a run is still waiting to be collected (engine/state/pending.json).
Needs GH_TOKEN and the gh tool.
"""
import glob
import json
import os
import subprocess

STATE = "engine/state"


def main():
    if os.path.exists(os.path.join(STATE, "pending.json")):
        print("A run is still on Kaggle (pending.json): nothing sent today.")
        return
    files = glob.glob(os.path.join(STATE, "waiting*.json"))
    if not files:
        print("Nothing waiting.")
        return
    jobs = []
    for f in files:
        try:
            jobs.append((json.load(open(f)).get("created_at", ""), f))
        except ValueError:
            print(f"⚠️ {f} is not valid JSON: skipped")
    if not jobs:
        return
    _, f = sorted(jobs)[0]
    w = json.load(open(f))
    subprocess.run(["gh", "workflow", "run", "engine.yml", "-f", f"job={w['job']}", "-f", "wait_minutes=170",
                    "-f", f"then_make={w.get('week', '')}"], check=True)
    subprocess.run(["git", "config", "user.name", "manzi-studio-bot"], check=True)
    subprocess.run(["git", "config", "user.email", "actions@users.noreply.github.com"], check=True)
    subprocess.run(["git", "rm", "-q", f], check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Manzi Engine: sent waiting job {w['job']}"], check=True)
    subprocess.run(["git", "push", "-q"], check=True)
    left = len(jobs) - 1
    print(f"Sent {w['job']} (then: {w.get('week') or 'nothing'}). Still waiting: {left}")


if __name__ == "__main__":
    main()
