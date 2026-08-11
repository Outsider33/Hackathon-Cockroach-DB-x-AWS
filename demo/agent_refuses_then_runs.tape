# agent_refuses_then_runs.tape -- the shot, as a script rather than a performance.
#
#   vhs demo/agent_refuses_then_runs.tape
#
# Renders demo/agent.mp4 and demo/agent.gif. Run it twice and the two files are the
# same, because `agent_loop.py` returns byte-identical output across runs -- the
# stress bench measured that -- and VHS drives the terminal from this file rather
# than from someone typing.
#
# 🎯 That is the point, not a convenience. A project whose whole claim is
# reproducibility should not have its demo depend on a human getting a line right.
# The rehearsal and the take are the same artefact.
#
# ⚠️ Requires vhs (github.com/charmbracelet/vhs) and its ffmpeg/ttyd dependencies.
# If it will not build, fall back to OBS and record the browser half only -- but
# then every retake is a fresh performance.

Output demo/agent.mp4
Output demo/agent.gif

Set Shell         bash
Set FontSize      18
Set Width         1280
Set Height        760
Set Padding       24
Set Theme         "Catppuccin Mocha"
Set TypingSpeed   45ms
# The playback pauses below are chosen for a viewer who is READING, not for someone
# who already knows what the output says. 2.5 s is roughly a line of dense text.
Set PlaybackSpeed 1.0

# --- Beat 1: the refusal. This is the shot that matters. -------------------
Type "python3 agent_loop.py --goal fea_run"
Sleep 600ms
Enter
Sleep 12s

# Let the verdict sit. A jury needs to read "I AM NOT RUNNING THIS" without the
# frame moving. Everything before this is setup; this is the sentence they keep.
Sleep 4s

Type "clear"
Enter
Sleep 500ms

# --- Beat 2: the same command, after a belief was written from the page ----
# ⚠️ SHOOT ORDER. Between beat 1 and beat 3 a belief must actually be committed
# on the demo page, in the browser. Record that half with OBS and cut it in here.
# Do NOT fake it: the whole film rests on nothing having changed except the memory.
Type "# a belief was just written on the demo page. Nothing else changed."
Sleep 2s
Enter
Sleep 800ms

Type "python3 agent_loop.py --goal fea_run"
Sleep 600ms
Enter
Sleep 12s
Sleep 3s

Type "clear"
Enter
Sleep 500ms

# --- Beat 3: a goal that is clear, so the acceptance cites its sources -----
# Without this beat the agent only ever says no, and a jury cannot tell refusal
# from incapacity.
Type "python3 agent_loop.py --goal fatigue_check_parent"
Sleep 600ms
Enter
Sleep 9s
Sleep 3s
