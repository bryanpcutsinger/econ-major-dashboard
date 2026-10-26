# Data update held: $n_failed gate(s) failed

The build made bundle `$candidate`, but it did not pass the hard gates. **Nothing changed on the
page.** The live bundle stays `$live`.

## Failed gates

$failed

## Gate report

```
$report
```

## What to do

1. Read the failed gates above. Each gate is defined in `spec/gates.yaml`.
2. If Census changed a code list or the data dictionary, update the map or the spec, then record
   the change in `spec/exception-ledger.md` before you rebuild.
3. Run the build again. The page changes only after every hard gate passes.
