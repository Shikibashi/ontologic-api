# Utility Adoption Visual Guide

## Codebase Coverage Map

```
📁 ontologic-api-main/
│
├── 📂 app/
│   ├── 📂 core/
│   │   ├── ✅ timeout_helpers.py         [NEW UTILITY - FULLY ADOPTED]
│   │   │   └── calculate_per_attempt_timeout()
│   │   │
│   │   ├── ✅ monitoring_helpers.py      [NEW UTILITY - PARTIAL]
│   │   │   └── safe_record_metric()
│   │   │       ├── ✅ Used in: ontologic.py (1x), documents.py (4x)
│   │   │       └── ❌ Missing in: workflows.py, auth.py, backup_router.py, admin_payments.py
│   │   │
│   │   └── ✅ subscription_helpers.py    [USES UTILITY]
│   │       └── safe_record_metric() used at lines 73, 128
│   │
│   ├── 📂 services/
│   │   ├── ✅ llm_manager.py              [FULLY ADOPTED]
│   │   │   ├── aquery() - uses calculate_per_attempt_timeout() ✓
│   │   │   ├── get_embedding() - uses calculate_per_attempt_timeout() ✓
│   │   │   ├── generate_splade_vector() - uses calculate_per_attempt_timeout() ✓
│   │   │   └── generate_dense_vector() - uses calculate_per_attempt_timeout() ✓
│   │   │
│   │   └── ✅ cache_service.py            [USES @with_timeout DECORATOR]
│   │       └── No changes needed - decorator handles timeout
│   │
│   ├── 📂 router/
│   │   ├── 🟡 workflows.py               [NEEDS 8 METRICS]
│   │   │   ├── ❌ Line 181: Draft creation error
│   │   │   ├── ❌ Line 229: Section generation error
│   │   │   ├── ❌ Line 268: Draft retrieval error
│   │   │   ├── ❌ Line 311: AI review error
│   │   │   ├── ❌ Line 354: Apply suggestions error
│   │   │   ├── ❌ Line 409: Delete draft error
│   │   │   ├── ❌ Line 471: List drafts error
│   │   │   └── ❌ Line 508: Validate draft error
│   │   │
│   │   ├── 🟡 ontologic.py               [NEEDS 7 REPLACEMENTS]
│   │   │   ├── ✅ Line 1028: Already uses safe_record_metric
│   │   │   └── ❌ Lines 226,229,942,970,1000,1005,1019: Should replace
│   │   │
│   │   ├── 🟡 documents.py               [PARTIALLY ADOPTED]
│   │   │   └── ✅ Lines 302,361,372,391: Already use safe_record_metric
│   │   │
│   │   ├── 🟡 auth.py                    [NEEDS 1 METRIC]
│   │   │   └── ❌ Line 124: Session not found error
│   │   │
│   │   ├── 🟡 backup_router.py           [NEEDS 2 METRICS]
│   │   │   ├── ❌ Line 384: Backup not found
│   │   │   └── ❌ Line 520: Restore backup not found
│   │   │
│   │   ├── 🟡 admin_payments.py          [NEEDS 1 METRIC]
│   │   │   └── ❌ Line 195: Refund payment not found
│   │   │
│   │   └── ✅ payments.py                [CORRECT 403 PATTERN]
│   │       └── Line 269: Uses 403 correctly ✓
│   │
│   └── 🟡 main.py                        [NEEDS 1 CONFIG CHECK]
│       ├── ✅ Line 192: Database localhost check ✓
│       ├── ✅ Line 202: Redis localhost check ✓
│       └── ❌ Line 209: ADD Qdrant localhost check
│
└── 📄 Generated Reports
    ├── UTILITY_ADOPTION_SUMMARY.md              (5.3 KB - Executive summary)
    ├── UTILITY_APPLICATION_QUICK_REF.md         (5.7 KB - Implementation guide)
    ├── UTILITY_APPLICATION_RECOMMENDATIONS.md   (18 KB - Full analysis)
    └── UTILITY_ADOPTION_DIAGRAM.md              (This file)
```

## Priority Heat Map

```
HIGH PRIORITY (12 changes - Error Handlers)
═══════════════════════════════════════════
🔴 workflows.py         ████████  (8 locations)
🔴 auth.py              █         (1 location)
🔴 backup_router.py     ██        (2 locations)
🔴 admin_payments.py    █         (1 location)

MEDIUM PRIORITY (8 changes - Success Paths)
════════════════════════════════════════════
🟠 ontologic.py         ███████   (7 locations)

LOW PRIORITY (1 change - Config)
═════════════════════════════════
🟡 main.py              █         (1 location)
```

## Implementation Flow

```
┌─────────────────────────────────────────────────────────┐
│  PHASE 1: HIGH PRIORITY ERROR HANDLERS (60-90 min)     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. app/router/workflows.py                            │
│     └── Add import + 8 safe_record_metric calls        │
│                                                         │
│  2. app/router/auth.py                                 │
│     └── Add import + 1 safe_record_metric call         │
│                                                         │
│  3. app/router/backup_router.py                        │
│     └── Add import + 2 safe_record_metric calls        │
│                                                         │
│  4. app/router/admin_payments.py                       │
│     └── Add import + 1 safe_record_metric call         │
│                                                         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  PHASE 2: MEDIUM PRIORITY SUCCESS PATHS (30-45 min)    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  5. app/router/ontologic.py                            │
│     └── Replace 7 chat_monitoring.record_* calls       │
│        with safe_record_metric                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  PHASE 3: LOW PRIORITY CONFIG CHECK (15 min)           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  6. app/main.py                                        │
│     └── Add Qdrant localhost validation at line 209    │
│                                                         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  PHASE 4: TESTING & VALIDATION (30-60 min)             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ✓ Run pytest suite                                    │
│  ✓ Verify metrics in dashboard                         │
│  ✓ Test graceful degradation                           │
│  ✓ Test production startup checks                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Status Summary

### ✅ Already Correct (No Changes Needed)

| Component | Status | Details |
|-----------|--------|---------|
| Timeout Helper | 100% Adopted | All 4 locations using it |
| 404/403 Status Codes | 100% Correct | All 18 usages appropriate |
| Database Config | ✓ Validated | Production startup check |
| Redis Config | ✓ Validated | Production startup check |

### 🟡 Needs Attention (21 Changes Required)

| Component | Status | Changes Needed |
|-----------|--------|----------------|
| Safe Record Metric | 23% Adopted | 20 more locations |
| Qdrant Config | Missing | 1 startup check |

## File Change Matrix

```
┌────────────────────────────┬──────────┬────────────┬──────────┐
│ File                       │ Priority │ Changes    │ Type     │
├────────────────────────────┼──────────┼────────────┼──────────┤
│ app/router/workflows.py    │   HIGH   │     8      │ Add      │
│ app/router/auth.py         │   HIGH   │     1      │ Add      │
│ app/router/backup_router.py│   HIGH   │     2      │ Add      │
│ app/router/admin_payments  │   HIGH   │     1      │ Add      │
│ app/router/ontologic.py    │  MEDIUM  │     7      │ Replace  │
│ app/main.py                │   LOW    │     1      │ Add      │
├────────────────────────────┼──────────┼────────────┼──────────┤
│ TOTAL                      │    -     │    21      │    -     │
└────────────────────────────┴──────────┴────────────┴──────────┘
```

## Quick Start Commands

```bash
# View executive summary
cat UTILITY_ADOPTION_SUMMARY.md

# View implementation guide
cat UTILITY_APPLICATION_QUICK_REF.md

# View detailed analysis
cat UTILITY_APPLICATION_RECOMMENDATIONS.md

# View this diagram
cat UTILITY_ADOPTION_DIAGRAM.md
```

## Impact Metrics

```
┌─────────────────────────────────────────┐
│  BEFORE                                 │
├─────────────────────────────────────────┤
│  ❌ 12 error handlers without metrics   │
│  ❌ 8 unsafe success path metrics       │
│  ❌ 1 missing config validation         │
│  ⚠️  Monitoring failures break requests │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│  AFTER (21 changes)                     │
├─────────────────────────────────────────┤
│  ✅ All error handlers have metrics     │
│  ✅ All metrics use safe recording      │
│  ✅ Complete config validation          │
│  ✅ Graceful degradation preserved      │
│  ✅ 100% observability coverage         │
└─────────────────────────────────────────┘
```

---

**Legend:**
- ✅ = Complete/Correct
- 🟡 = Partially adopted
- ❌ = Missing implementation
- 🔴 = High priority
- 🟠 = Medium priority
