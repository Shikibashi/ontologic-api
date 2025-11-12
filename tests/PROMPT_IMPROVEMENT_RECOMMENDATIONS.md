# Prompt Improvement Recommendations

**Generated:** 2025-09-30
**Based on:** 39 prompt comparisons
**Key Issues:** Short responses (67% expected length), low keyword overlap (11.6%)

---

## Executive Summary

Your prompts are producing responses that are **33% shorter** than expected and missing **88% of expected philosophical concepts**. The main issue is that prompts are too brief and don't explicitly request the depth, breadth, and specific content needed for comprehensive philosophical analysis.

**Good News:** The LLM is capable of producing quality responses - the prompts just need more explicit guidance.

---

## Critical Issues Identified

### 1. **Vague Prompts Yield Brief Responses**

**Problem Example:**
```
Query: "A runaway train is heading toward five workers while a single
worker stands on the side track. Should the lever be pulled?"

Result: 456 characters (19% of expected length)
```

**What's Missing:**
- No request for detailed analysis
- No specification of which ethical frameworks to discuss
- No mention of philosophers or philosophical concepts
- No length guidance

**Actual Response:**
> "The decision to pull the lever involves a moral dilemma between minimizing
> harm and respecting individual lives..."

**Expected Response Should Include:**
- Utilitarian analysis (Bentham, Mill)
- Deontological perspective (Kant's categorical imperative)
- Virtue ethics framework (Aristotelian phronesis)
- Care ethics perspective
- 4-5 paragraphs of depth

### 2. **Missing Explicit Instructions**

**Better-Performing Prompts Include:**
- "Compose an immersive explanation from Aristotle..."
- "Provide a comprehensive analysis..."
- "Compare and contrast [specific frameworks]..."
- "Reference key philosophers and their arguments..."

**Worse-Performing Prompts Are:**
- Single questions without context
- No mention of desired depth
- No specification of frameworks to cover

### 3. **System Prompt May Be Too Concise**

The responses suggest the system might be instructed to be brief. Check your system prompt for:
- "Be concise"
- "Keep responses brief"
- "Summarize"
- Any brevity instructions

---

## Specific Recommendations

### A. Add Explicit Length & Detail Guidance

**For Every Prompt, Add:**

```
Provide a comprehensive philosophical analysis addressing this question.
Your response should:
- Be 3-4 paragraphs minimum
- Reference specific philosophers and their arguments
- Discuss multiple ethical/philosophical frameworks
- Use precise philosophical terminology
- Demonstrate depth of philosophical reasoning
```

### B. Specify Frameworks to Discuss

**Before:**
```
Should the lever be pulled?
```

**After:**
```
Should the lever be pulled? Analyze this dilemma from utilitarian,
deontological, and virtue ethics perspectives. Reference key thinkers
like Bentham, Mill, Kant, and Aristotle. Compare how each framework
would approach the decision and what tensions arise between them.
```

### C. Use "Immersive Mode" for Depth

Prompts with `immersive=True` performed **20% better** on average:

**Good Example:**
```
Compose an immersive explanation from Aristotle about the purpose of
human life in contemporary society.

Result: 76% length ratio, 14.8% keyword similarity ✓
```

### D. Request Specific Content

**For Ethical Dilemmas:**
```
In your analysis, include:
1. Consequentialist reasoning (utility calculus)
2. Deontological considerations (moral duties, rights)
3. Virtue ethics perspective (character and practical wisdom)
4. Modern applications and edge cases
5. Tensions between frameworks
```

**For Epistemology:**
```
In your analysis, include:
1. Historical context and key figures
2. The philosophical problem or puzzle
3. Major responses and counter-arguments
4. Contemporary relevance
5. Implications for knowledge and belief
```

**For Political Philosophy:**
```
In your analysis, include:
1. Core principles of each theory
2. Key thinkers and their arguments
3. Practical applications
4. Critiques and counterarguments
5. Contemporary debates
```

### E. Temperature Settings

**Findings:**
- Temperature 0.3: More focused but possibly too brief
- Temperature 0.5-0.7: Better for expansive philosophical analysis

**Recommendation:** Use temperature 0.6-0.7 for prompts requiring comprehensive analysis.

### F. Revised System Prompt Suggestions

**Current Issues Suggest:**
Your system prompt may be instructing brevity. Consider adding:

```
You are a comprehensive philosophy assistant. When answering questions:

1. DEPTH: Provide thorough, detailed analysis (3-5 paragraphs minimum)
2. SPECIFICITY: Reference specific philosophers, arguments, and concepts
3. FRAMEWORKS: Discuss multiple relevant philosophical perspectives
4. PRECISION: Use accurate philosophical terminology
5. ENGAGEMENT: Make complex ideas accessible without oversimplifying

Do not be overly concise. Philosophy requires nuance and depth.
Users expect comprehensive, well-developed responses that demonstrate
deep engagement with the material.
```

---

## Priority Fixes by Prompt Category

### **Ethical Dilemmas** (Worst Performers)

**Affected Prompts:**
- Trolley Problem (19% length ratio)
- Corporate Ethics (36%)
- AI Bias (35%)
- Surveillance Privacy (31%)

**Required Changes:**
1. Add "Analyze from utilitarian, deontological, and virtue ethics perspectives"
2. Specify 3-4 paragraph minimum
3. Request specific philosopher references
4. Ask for comparison of frameworks

**Example Rewrite:**

```
Before:
"A runaway train is heading toward five workers while a single worker
stands on the side track. Should the lever be pulled?"

After:
"A runaway train is heading toward five workers while a single worker
stands on the side track. Should the lever be pulled?

Provide a comprehensive ethical analysis addressing this classic trolley
problem. Your response should:
- Analyze the dilemma from utilitarian, deontological, and virtue ethics
  perspectives
- Reference key philosophers (Bentham, Mill, Kant, Aristotle)
- Discuss the tension between maximizing utility and respecting individual
  rights
- Address the doctrine of doing vs. allowing harm
- Consider how each framework would justify their position
- Be at least 3-4 paragraphs with philosophical depth

Demonstrate how different ethical theories yield different conclusions
and why this dilemma remains philosophically significant."
```

### **Epistemology** (Mixed Performance)

**Better When:**
- Explicitly asking about "the problem" (e.g., "Gettier problem")
- Requesting comparison of positions

**Worse When:**
- Too open-ended
- No framework specification

**Recommendation:**
Always structure epistemology prompts to request:
1. The philosophical problem/puzzle
2. Historical responses
3. Contemporary debate
4. Specific thought experiments or cases

### **Applied Ethics** (Medium Performance)

**Works Well:**
- Prompts that specify stakeholders
- Prompts that ask for multiple perspectives

**Improvement Needed:**
- Add "discuss obligations of [specific groups]"
- Request analysis of rights, harms, duties
- Ask for practical policy implications

### **Historical Philosophy** (Best Performance)

**Why It Works:**
- "Immersive" prompts explicitly ask for philosopher's voice
- Clear specification of philosopher and topic

**Keep Doing:**
- "Explain from [Philosopher]'s perspective"
- "How would [Philosopher] respond to..."
- Immersive persona mode

---

## Testing Protocol

### Step 1: Rewrite Top 5 Worst Performers

**Priority Order:**
1. prompt_001_trolley_problem (19% length, 8.4% keywords)
2. prompt_011_gettier_problem (26% length, 6.5% keywords)
3. prompt_006_surveillance_privacy (31% length, 7.8% keywords)
4. prompt_005_medical_autonomy (32% length, 10.4% keywords)
5. prompt_003_ai_bias (35% length, 6.7% keywords)

### Step 2: A/B Test

For each rewritten prompt:
1. Run original version
2. Run improved version
3. Compare:
   - Length ratio (target: > 0.8)
   - Keyword similarity (target: > 0.15)
   - Presence of expected frameworks
   - Philosophical depth

### Step 3: Measure Improvement

**Success Criteria:**
- Average length ratio > 0.8 (currently 0.67)
- Average keyword similarity > 0.15 (currently 0.116)
- < 5 prompts with length ratio < 0.5 (currently 11)
- All responses mention at least 2 philosophical frameworks

---

## Quick Wins

### 1. **Universal Prefix**

Add to ALL prompts:

```
[Provide a comprehensive philosophical analysis. Reference specific
philosophers and discuss multiple perspectives. Be thorough and detailed.]

[Original prompt question here]
```

### 2. **Framework Checklist**

For ethical prompts, append:

```
Address: utilitarian analysis, deontological concerns, virtue ethics
perspective, and practical implications.
```

### 3. **Length Anchor**

Add to system prompt:

```
Standard responses should be 400-600 words (3-4 substantial paragraphs).
Brief responses under 200 words are insufficient for philosophical depth.
```

---

## Example: Complete Prompt Transformation

### BEFORE (19% length ratio)

```
Query: A runaway train is heading toward five workers while a single
worker stands on the side track. Should the lever be pulled?

Temperature: 0.3
Immersive: false
```

### AFTER (Target: 80%+ length ratio)

```
Query: A runaway train is heading toward five workers while a single
worker stands on the side track. Should the lever be pulled?

Provide a comprehensive ethical analysis of this classic trolley problem.
Your response must:

1. UTILITARIAN ANALYSIS: Discuss Jeremy Bentham and John Stuart Mill's
   approach. How would classical utilitarianism evaluate this choice?
   Address the arithmetic of consequences and the principle of maximizing
   overall well-being.

2. DEONTOLOGICAL PERSPECTIVE: Examine Kant's categorical imperative.
   Why might a Kantian object to pulling the lever? Discuss the doctrine
   of double effect and the distinction between killing vs. letting die.

3. VIRTUE ETHICS: Apply Aristotelian virtue ethics. What would a person
   of practical wisdom (phronesis) do? How does this framework change the
   question from "what action" to "what kind of person"?

4. CONTEMPORARY DEBATES: Discuss why this dilemma remains significant
   in applied ethics. Address the tension between consequentialism and
   deontology.

Your response should be 3-4 substantial paragraphs demonstrating deep
philosophical engagement. Use precise terminology and reference specific
arguments from the philosophical tradition.

Temperature: 0.7
Immersive: false
```

---

## Immediate Action Items

- [ ] Review and update system prompt (remove brevity instructions, add depth requirements)
- [ ] Rewrite 5 worst-performing prompts with explicit framework specifications
- [ ] Test revised prompts and compare metrics
- [ ] Update temperature settings (0.6-0.7 for comprehensive analysis)
- [ ] Add universal "depth and detail" prefix to all prompts
- [ ] Consider increasing `max_tokens` if currently limited
- [ ] Document expected word count ranges per prompt type

---

## Conclusion

Your LLM is responding accurately to what you're asking - the issue is that you're asking for too little. By being explicit about depth, breadth, frameworks, and expected content, you can easily achieve 80%+ of your target response quality.

**Key Insight:** Philosophy requires specification. The difference between "Should the lever be pulled?" and "Should the lever be pulled? Analyze from utilitarian, deontological, and virtue ethics perspectives, referencing Bentham, Mill, and Kant" is the difference between a 200-word response and a 600-word comprehensive analysis.
