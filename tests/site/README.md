# Page checks (step 10, spec/front-end.yaml done checks 2-7)

Serve the repo root on this computer only, then run the harness in headless Chrome:

    python3 -m http.server 8765 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
      --user-data-dir=/tmp/harness-profile --virtual-time-budget=300000 \
      --dump-dom http://127.0.0.1:8765/tests/site/harness.html

The JSON in `<pre id="out">` lists: content heights (max over every major and switch, at
320 / 380 / 640 px), horizontal overflow, chart-vs-table number mismatches, keyboard problems,
and the five-frame sync result. Pass = `overflow`, `mismatch`, `errors` empty; every keyboard
`problems` empty; every `sync` value equal to the pick.

`shot.html?w=380&h=1700&panel=compare&major=Nursing` wraps one panel for a screenshot
(`--screenshot`); leave `panel` empty for the full explorer.
