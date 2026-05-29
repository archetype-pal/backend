# Legacy Migration Audit

Status: `warn`

| Database | Public tables |
| --- | ---: |
| `old_arch` | 142 |
| `test_db` | 52 |

## Entity Mappings

| Status | Entity | Legacy rows | Target rows | Strategy |
| --- | --- | ---: | ---: | --- |
| `warn` | Dates | 594 | 610 | id-preserved with target-only date seeds |
| `warn` | Edit events | 0 | 22 | target-only workflow table |
| `ok` | Item formats | 20 | 20 | id-preserved |
| `ok` | Bibliographic sources | 40 | 40 | id-preserved |
| `ok` | Repositories | 9 | 9 | id-preserved transformed fields |
| `ok` | Current items | 718 | 718 | id-preserved transformed fields |
| `ok` | Historical items | 713 | 713 | id-preserved transformed lookups |
| `ok` | Historical item descriptions | 703 | 703 | id-preserved transformed fields |
| `ok` | Catalogue numbers | 1414 | 1414 | id-preserved transformed fields |
| `warn` | Item parts | 712 | 713 | id-preserved with placeholder |
| `ok` | Item images | 3277 | 3277 | id-preserved transformed fields |
| `ok` | Image texts | 899 | 899 | content-preserved, ids not preserved |
| `ok` | Image text status transitions | 0 | 0 | target-only workflow table |
| `warn` | Historical item date assessments | 0 | 22 | target-only derived metadata |
| `warn` | Scribes | 2 | 3 | id-preserved with placeholder |
| `ok` | Scripts | 0 | 0 | id-preserved |
| `ok` | Hands | 696 | 696 | id-preserved transformed fields |
| `ok` | Hand image links | 715 | 715 | id-preserved |
| `ok` | Characters | 103 | 103 | id-preserved transformed type |
| `warn` | Allographs | 102 | 103 | id-preserved with placeholder |
| `ok` | Components | 15 | 15 | id-preserved |
| `ok` | Features | 54 | 54 | id-preserved |
| `ok` | Component feature links | 76 | 76 | id-preserved |
| `warn` | Allograph components | 81 | 80 | id-preserved with one omitted duplicate/stale row |
| `warn` | Allograph component feature links | 69 | 68 | id-preserved with one omitted duplicate/stale row |
| `ok` | Positions | 17 | 17 | id-preserved rename |
| `ok` | Allograph position links | 337 | 337 | ids not preserved |
| `warn` | Annotations | 24584 | 24586 | annotation ids preserved with target extras |
| `warn` | Graph components | 3103 | 3027 | mostly id-preserved, filtered |
| `warn` | Graph component feature links | 3367 | 3303 | mostly id-preserved, filtered |
| `warn` | Graph position links | 1491 | 1485 | ids not preserved, filtered |
| `ok` | Publications | 61 | 61 | id-preserved transformed fields |
| `ok` | Publication keyword links | 67 | 67 | ids not preserved |
| `ok` | Carousel items | 8 | 8 | id-preserved transformed fields |
| `ok` | Worksets | 0 | 0 | target-only feature table |

## Checks

| Status | Check | Summary |
| --- | --- | --- |
| `warn` | Publication author mapping | Publication author ids are not a safe migration key because target users were seeded before legacy users. Map authors by username/email or choose an explicit fallback author. |
| `warn` | Annotation shape | Target text/editorial annotations retain allograph/hand values. This is valid under the current database constraint but differs from the model comment that treats those links as optional. |
| `ok` | Legacy text exclusions | Non-empty legacy text XML rows: 899; target ImageText rows: 899. |

## Mapping Details

### Dates

- Status: `warn`
- Strategy: id-preserved with target-only date seeds
- Notes: Legacy sortable dates map to common.Date. Target ids 1-16 are newer target-only date seeds.
- Missing in target: 0; sample: `[]`
- Extra in target: 16; sample: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]`

### Edit events

- Status: `warn`
- Strategy: target-only workflow table
- Notes: Current append-only editorial audit log; not imported from old_arch.

### Item parts

- Status: `warn`
- Strategy: id-preserved with placeholder
- Notes: The target has a synthetic -1 placeholder part; historical linkage comes from digipal_itempartitem.
- Missing in target: 0; sample: `[]`
- Extra in target: 1; sample: `[-1]`

### Historical item date assessments

- Status: `warn`
- Strategy: target-only derived metadata
- Notes: Current per-item date assessment metadata; created from current target date metadata, not old_arch.

### Scribes

- Status: `warn`
- Strategy: id-preserved with placeholder
- Notes: The target has a synthetic -1 scribe for unmapped/unknown data.
- Missing in target: 0; sample: `[]`
- Extra in target: 1; sample: `[-1]`

### Allographs

- Status: `warn`
- Strategy: id-preserved with placeholder
- Notes: The target has a synthetic -1 allograph for text/unmapped annotations.
- Missing in target: 0; sample: `[]`
- Extra in target: 1; sample: `[-1]`

### Allograph components

- Status: `warn`
- Strategy: id-preserved with one omitted duplicate/stale row
- Notes: One legacy row is absent in the inspected target.
- Missing in target: 1; sample: `[46]`
- Extra in target: 0; sample: `[]`

### Allograph component feature links

- Status: `warn`
- Strategy: id-preserved with one omitted duplicate/stale row
- Notes: One legacy row is absent in the inspected target.
- Missing in target: 1; sample: `[127]`
- Extra in target: 0; sample: `[]`

### Annotations

- Status: `warn`
- Strategy: annotation ids preserved with target extras
- Notes: Legacy annotations become target Graph rows. Image annotations join through digipal_graph; text/editorial rows remain annotation-like.
- Missing in target: 0; sample: `[]`
- Extra in target: 2; sample: `[27336, 27337]`

### Graph components

- Status: `warn`
- Strategy: mostly id-preserved, filtered
- Notes: Rows tied to omitted/legacy-only graph material are not fully represented.

### Graph component feature links

- Status: `warn`
- Strategy: mostly id-preserved, filtered
- Notes: Tracks the graph component filtering.

### Graph position links

- Status: `warn`
- Strategy: ids not preserved, filtered
- Notes: Legacy graph aspects become target graph positions, are re-keyed, and are filtered with graph rows.


## Check Details

### Publication author mapping

Publication author ids are not a safe migration key because target users were seeded before legacy users. Map authors by username/email or choose an explicit fallback author.

```json
[
  {
    "legacy_id": 2,
    "legacy_username": "sbrookes",
    "post_count": 36,
    "target_username": "ali"
  },
  {
    "legacy_id": 3,
    "legacy_username": "pstokes",
    "post_count": 13,
    "target_username": "faidon"
  },
  {
    "legacy_id": 4,
    "legacy_username": "jdavies",
    "post_count": 2,
    "target_username": "luca"
  },
  {
    "legacy_id": 5,
    "legacy_username": "dbroun",
    "post_count": 3,
    "target_username": "stewart"
  },
  {
    "legacy_id": 6,
    "legacy_username": "twebber",
    "post_count": 1,
    "target_username": "admin"
  }
]
```

### Annotation shape

Target text/editorial annotations retain allograph/hand values. This is valid under the current database constraint but differs from the model comment that treats those links as optional.

```json
[
  {
    "annotation_total": 24584,
    "editorial_annotations": 1,
    "editorial_graphs": 2,
    "graph_total": 24586,
    "image_graphs": 20536,
    "image_graphs_missing_required_fk": 0,
    "image_like_annotations": 20535,
    "non_image_graphs_with_legacy_fk": 4049,
    "text_annotations": 4048,
    "text_graphs": 4048
  }
]
```
