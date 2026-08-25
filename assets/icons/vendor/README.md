# Vendor icon packs (user-supplied, git-ignored)

Drop official or third-party icon packs here, one folder per pack:

```
assets/icons/vendor/
  aws/        s3.svg, ec2.svg, lambda.svg, ...
  gcp/        bigquery.svg, gke.svg, ...
  kubernetes/ pod.svg, service.svg, ...
```

At render time an exact filename match here **wins over** the bundled Tabler
icons and the semantic alias table, so `{"icon": "s3"}` renders your
`vendor/aws/s3.svg` when present and falls back to a generic icon when not.

Rules:

- SVG files only; 24x24 viewBox stroke icons blend best with the hand-drawn
  style. Colored official logos are restroked in the theme ink.
- **License**: most official architecture icon sets (AWS, Azure, GCP) allow
  use in diagrams but not redistribution. That is why this folder is
  git-ignored — download packs yourself; do not commit them.
- See `references/vendor-icons.md` for download sources and
  `scripts/icon_search.py` for an optional Iconify-powered search/fetch tool.
