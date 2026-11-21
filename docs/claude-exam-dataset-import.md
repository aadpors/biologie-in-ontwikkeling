# Claude exam dataset import

This importer stages the complete 2024–2026 havo/vwo dataset in an isolated
directory. It does **not** change the live exam library, the current
`examenoefenen.html`, or the legacy snippet collection.

## Run locally

```bash
python scripts/import_claude_exam_dataset.py biologie-examens-havo-vwo-2024-2026.zip \
  --output-dir /tmp/claude-exam-dataset
```

The script validates ZIP CRCs, the manifest's complete exam list, every
manifest SHA-256 and byte count, all 12 exam JSON files, unique question IDs,
question types, source provenance, and one valid PNG snippet per question.
It refuses to overwrite an existing destination.

## Dataset facts and editorial status

The supplied archive declares 12 exams and 519 questions. Its own audit reports
describe the visual review performed during preparation. They also state that
answer-key/scoring extraction is best-effort and that independent teacher
validation remains necessary. Passing this importer means structural integrity
only; it is **not** a pedagogical approval or a guarantee that every answer key
and marking point is correct.

MCQ may be automatically checked only when a definitive correct answer is
present. Open responses must be self-assessed against the official marking
scheme; free-text similarity must never be presented as official grading.

## Intended integration sequence

1. Stage into a new versioned directory, never over the live data.
2. Review the generated audit reports and visually sample every exam and every
   question image at full resolution.
3. Reconcile each question's official marking scheme with the source PDF.
4. Run the browser regression tests against the staged dataset.
5. Only after explicit validation, switch both the exam library and
   Examenoefenen to the same canonical data source.
6. Archive legacy snippet-only generators and workflows; do not delete them.

The dataset ZIP and its 519 image files are not committed by this code-only
change. They must be transferred as binary assets in a separate staging step.
