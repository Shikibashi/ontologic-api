# Sophia Specification Coverage Analysis

## Summary
- **Current test prompts**: 37
- **Sophia specification prompts**: 37
- **Matching prompts**: 4 (10.8%)
- **Missing from test suite**: 33 (89.2%)

## Matching Prompts (4/37)

These prompts exist in both the test suite and Sophia specs:

| Prompt ID | Status | Issues |
|-----------|--------|--------|
| prompt_001_trolley_problem | ❌ Failing | Missing "care ethics" keyword; word count 288 (need 350-500) |
| prompt_014_scientific_realism | ❌ Failing | Missing "unobservables" keyword |
| prompt_034_error_theory | ❌ Failing | Missing "projectivism" keyword |
| prompt_035_virtue_vs_care | ❌ Failing | Word count 371 (need 400-550) |

## Missing from Current Test Suite (33/37)

These prompts from your Sophia specification are NOT in the current test suite:

### Ethical Dilemmas (6 missing)
1. ❌ prompt_002_ai_job_automation
2. ❌ prompt_003_universal_basic_income
3. ❌ prompt_004_gene_editing
4. ❌ prompt_005_privacy_security
5. ❌ prompt_006_climate_duty
6. ❌ prompt_007_free_speech_harm

### Applied Ethics (8 missing)
7. ❌ prompt_008_animal_rights
8. ❌ prompt_009_immigration
9. ❌ prompt_010_death_penalty
10. ❌ prompt_022_abortion
11. ❌ prompt_023_euthanasia
12. ❌ prompt_024_affirmative_action
13. ❌ prompt_025_environmental_justice (duplicate name confusion with prompt_004 in test)
14. ❌ prompt_026_medical_autonomy (duplicate name confusion with prompt_005 in test)

### Philosopher Personas (8 missing)
15. ❌ prompt_011_kant_lying
16. ❌ prompt_012_mill_higher_pleasures
17. ❌ prompt_013_rawls_justice
18. ❌ prompt_019_aristotle_eudaimonia (duplicate name confusion with prompt_007 in test)
19. ❌ prompt_020_nozick_experience_machine
20. ❌ prompt_021_singer_poverty
21. ❌ prompt_037_sartre_authenticity

### Epistemology & Metaphysics (6 missing)
22. ❌ prompt_015_gettier (similar to prompt_011_gettier_problem in test but different query)
23. ❌ prompt_016_mind_body
24. ❌ prompt_017_free_will_determinism
25. ❌ prompt_018_meaning_of_life
26. ❌ prompt_030_problem_of_induction (duplicate name confusion with prompt_013 in test)
27. ❌ prompt_031_feminist_epistemology (duplicate name confusion with prompt_015 in test)

### Advanced Topics (5 missing)
28. ❌ prompt_027_surveillance_privacy (duplicate name confusion with prompt_006 in test)
29. ❌ prompt_028_virtue_ai_design (duplicate name confusion with prompt_009 in test)
30. ❌ prompt_029_autonomous_weapons (duplicate name confusion with prompt_010 in test)
31. ❌ prompt_032_personal_identity_teleportation (duplicate name confusion with prompt_018 in test)
32. ❌ prompt_033_civil_disobedience (duplicate name confusion with prompt_021 in test)
33. ❌ prompt_036_philosophy_methodology (duplicate name confusion with prompt_037 in test)

## Current Test Suite Prompts NOT in Sophia Specs (33/37)

These are in the test suite but have no Sophia validation specs:

1. prompt_002_corporate_ethics
2. prompt_003_ai_bias
3. prompt_004_environmental_justice (different from spec version)
4. prompt_005_medical_autonomy (different from spec version)
5. prompt_006_surveillance_privacy (different from spec version)
6. prompt_007_aristotle_eudaimonia (different from spec version)
7. prompt_008_rawls_healthcare
8. prompt_009_virtue_ai_design (different from spec version)
9. prompt_010_autonomous_weapons (different from spec version)
10. prompt_011_gettier_problem (different from spec version)
11. prompt_012_cartesian_skepticism
12. prompt_013_problem_of_induction (different from spec version)
13. prompt_015_feminist_epistemology (different from spec version)
14. prompt_016_ship_of_theseus
15. prompt_017_modal_realism
16. prompt_018_personal_identity_teleportation (different from spec version)
17. prompt_019_rawls_nozick
18. prompt_020_social_contract_digital_privacy
19. prompt_021_civil_disobedience (different from spec version)
20. prompt_022_anarchism_common_good
21. prompt_023_logical_fallacies
22. prompt_024_validity_soundness
23. prompt_025_deductive_vs_inductive
24. prompt_026_assisted_suicide
25. prompt_027_crispr_ethics
26. prompt_028_animal_research
27. prompt_029_art_definition
28. prompt_030_beauty_subjective
29. prompt_031_aesthetic_value_society
30. prompt_032_moral_realism
31. prompt_033_moral_motivation
32. prompt_036_purpose_of_philosophy
33. prompt_037_philosophy_methodology (different from spec version)

## Recommendations

### Option 1: Align Test Suite to Sophia Specs
Replace the current 37 test prompts with the 37 prompts defined in your Sophia specification. This would:
- Ensure consistent validation against your Expected Output criteria
- Enable proper testing of philosopher persona modes (8 prompts)
- Cover the specific ethical dilemmas you want to test

### Option 2: Create Dual Validation Specs
Keep both sets of prompts but create specs for all 70 unique prompts (37 current + 33 missing from Sophia specs). This would:
- Maintain current test coverage
- Add Sophia specification coverage
- Require more specification work

### Option 3: Focus on Core Coverage
Identify which prompts from each set are most critical and merge them into a single comprehensive test suite of ~40-50 prompts.

## Next Steps

**Immediate actions to fix current validation:**
1. Fix the 4 matching prompts by updating queries to include missing keywords
2. Decide whether to replace the test suite or create dual coverage
3. If replacing: Generate the 33 missing prompts from your Sophia specs
4. If dual coverage: Create validation specs for the 33 test prompts without specs

**Would you like me to:**
- A) Replace the test suite with your 37 Sophia-specified prompts?
- B) Generate specs for the current 33 unspecified test prompts?
- C) Create a merged test suite with both sets?
