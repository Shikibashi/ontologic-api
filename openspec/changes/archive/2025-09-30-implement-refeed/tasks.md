## 1. Implementation
- [x] 1.1 Respect `refeed` param in `/ask_philosophy` by passing through to `gather_points_and_sort`
- [x] 1.2 Respect `refeed` and `raw_mode` interplay in `/query_hybrid`
- [x] 1.3 Enable meta refeed in `QdrantManager.gather_points_and_sort` when `refeed=true`
- [x] 1.4 Add unit tests for refeed path in services
- [x] 1.5 Add contract tests for both endpoints with `refeed=true|false`
- [x] 1.6 Update spec examples where behavior changes
- [x] 1.7 Run `openspec validate implement-refeed --strict` and fix issues
