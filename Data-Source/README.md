# Data-Source

Drop source PDFs here for ingestion. This folder is gitignored — textbook PDFs
are large and copyrighted, never committed to the repo.

## Convention

```
Data-Source/
  <Writer>/
    1st-Paper/
      *.pdf
    2nd-Paper/
      *.pdf
```

Example:

```
Data-Source/
  Dr-Giasuddin-Ahmed/
    1st-Paper/
      chapter-1-vector.pdf
      chapter-2-motion.pdf
    2nd-Paper/
      chapter-1-electric-field.pdf
```

Writer folder names should be short and consistent — they're passed directly
to the ingestion CLI's `--writer` flag and stored as-is in Qdrant payload
metadata (used for citations and multi-writer attribution in answers).

## Board questions

Past HSC board exam questions go in a parallel `Board-Questions/` folder at
the same level, organized by paper:

```
Data-Source/
  Board-Questions/
    1st-Paper/
      *.pdf
    2nd-Paper/
      *.pdf
```
