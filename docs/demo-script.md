# Three-minute demonstration script

## 0:00-0:25 - The blind spot

“Both revisions are healthy. The candidate receives zero production traffic. A normal smoke test returns HTTP 200, but that does not tell us whether this particular change is safe.”

Show the stable and candidate cards and the concurrency diff.

## 0:25-0:55 - Change-aware planning

“Gemini sees that concurrency changed from 4 to 32. Under a fixed experiment budget, it forms a contention hypothesis and selects bounded paired load rather than an unrelated contract test.”

Show the structured hypothesis, selected experiment, budget, and fixed threshold.

## 0:55-1:35 - Evidence and decision

Run the analysis. Show that health and smoke pass on both revisions, then show the candidate p95 regression. Emphasize:

“Gemini did not choose the threshold and cannot override the outcome. The policy engine returns BLOCK from the measured evidence.”

## 1:35-2:15 - A different change, a different test

Switch to the API response change. Show the field rename and number-to-string change.

“The infrastructure did not change, so Gemini does not run load. It selects contract compatibility. Both endpoints return 200, but the candidate breaks an existing client contract.”

Run the second analysis and show `BLOCK` with the missing `total` field evidence.

## 2:15-2:45 - Why this is not Cloud Deploy replacement

“Cloud Deploy can run verification tasks teams configure. ReleaseProof supplies the change-specific investigation plan and paired pre-traffic evidence. It can become a verification task inside Cloud Deploy.”

## 2:45-3:00 - Close

“ReleaseProof does not ask teams to trust an AI release recommendation. AI plans the investigation; evidence makes the decision.”

