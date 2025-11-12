#!/usr/bin/env python
"""Parse documentation and enhance prompts with explicit instructions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()

# Documentation mapping: Prompt Example Number -> Prompt ID
DOC_TO_PROMPT_MAPPING = {
    1: "prompt_001_trolley_problem",
    2: "prompt_002_corporate_ethics",
    3: None,  # Kant vs Mill comparison - not in current catalog
    4: None,  # Rorty truth - not in current catalog
    5: "prompt_003_ai_bias",
    6: None,  # Journalism ethics - not in current catalog
    7: "prompt_007_aristotle_eudaimonia",
    8: "prompt_008_rawls_healthcare",
    9: None,  # Autonomous vehicle - variant of trolley
    10: None,  # AI rights - not in current catalog
    11: "prompt_011_gettier_problem",
    12: "prompt_012_cartesian_skepticism",
    13: None,  # Internalist vs externalist - covered in feminist epistemology?
    14: None,  # Free will compatibility - not in current catalog
    15: "prompt_016_ship_of_theseus",
    16: "prompt_017_modal_realism",
    17: "prompt_019_rawls_nozick",
    18: "prompt_020_social_contract_digital_privacy",
    19: "prompt_022_anarchism_common_good",
    20: "prompt_023_logical_fallacies",
    21: "prompt_024_validity_soundness",
    22: "prompt_025_deductive_vs_inductive",
    23: "prompt_026_assisted_suicide",
    24: "prompt_027_crispr_ethics",
    25: "prompt_028_animal_research",
    26: "prompt_029_art_definition",
    27: "prompt_030_beauty_subjective",
    28: None,  # Political authority justification - variant?
    29: None,  # Equality of outcome vs opportunity - not in current catalog
    30: "prompt_032_moral_realism",
    31: "prompt_033_moral_motivation",
    32: "prompt_036_purpose_of_philosophy",
    33: None,  # Moral language - variant of error theory?
    34: "prompt_031_aesthetic_value_society",
    35: None,  # Philosophy's limits - variant of purpose?
    36: None,  # Moral relativism - covered by moral realism?
    37: None,  # Aesthetic vs ethical value conflict - not in catalog
}

# Enhanced query templates based on documentation
ENHANCED_QUERIES = {
    "prompt_001_trolley_problem": {
        "query": """A runaway train is heading toward five workers while a single worker stands on the side track. Should the lever be pulled?

Analyze this scenario using utilitarianism, deontology, and virtue ethics:
1. UTILITARIAN PERSPECTIVE: Explain how this approach focuses on maximizing overall well-being
2. DEONTOLOGICAL PERSPECTIVE: Describe how this view respects moral rules and duties
3. VIRTUE ETHICS ANALYSIS: Analyze how a virtuous person would act in this situation
4. Provide a balanced conclusion without asserting a single "correct" answer""",
        "doc_reference": "Prompt Example 1"
    },

    "prompt_002_corporate_ethics": {
        "query": """Is it ethical for a corporation to prioritize profits over environmental sustainability?

Analyze this question from multiple stakeholder perspectives:
1. SHAREHOLDERS: Address the ethical obligations corporations have to shareholders (fiduciary duties)
2. EMPLOYEES: Discuss broader responsibilities to employees (livelihoods and working conditions)
3. AFFECTED COMMUNITIES: Consider the impact of environmental harm on local and global communities
4. Compare stakeholder theory with shareholder primacy and offer a reflective conclusion""",
        "doc_reference": "Prompt Example 2"
    },

    "prompt_003_ai_bias": {
        "query": """An AI hiring algorithm disproportionately rejects candidates from minority backgrounds.

Analyze the ethical implications and provide solutions:
1. ETHICAL ISSUES: Identify the core problems - fairness, bias, and justice
2. ROOT CAUSES: Discuss why such biases arise (training data, systemic discrimination, algorithmic design)
3. PRACTICAL SOLUTIONS: Propose actionable steps like re-training the model, auditing data, or using fairness-aware algorithms
4. Consider both short-term fixes and long-term systemic changes""",
        "doc_reference": "Prompt Example 5"
    },

    "prompt_007_aristotle_eudaimonia": {
        "query": """Answer the following question as if you were Aristotle: 'What is the purpose of human life in contemporary society, and how can one achieve it?'

Your response should:
1. Adopt Aristotle's tone and reasoning style
2. Reference key Aristotelian ideas: eudaimonia (human flourishing), virtue ethics, and the "golden mean"
3. Apply ancient concepts to contemporary challenges
4. Discuss the role of virtue cultivation and practical wisdom (phronesis)""",
        "doc_reference": "Prompt Example 7"
    },

    "prompt_008_rawls_healthcare": {
        "query": """You are John Rawls. A policymaker asks you whether universal healthcare is just. How would you respond?

Your response should:
1. Apply Rawlsian principles, particularly the veil of ignorance and the difference principle
2. Analyze how universal healthcare aligns with fairness and equality
3. Consider the original position thought experiment
4. Maintain consistency with Rawls's moral and political framework
5. Address potential objections from a Rawlsian perspective""",
        "doc_reference": "Prompt Example 8"
    },

    "prompt_011_gettier_problem": {
        "query": """Explain the Gettier problem and why it challenges the traditional definition of knowledge as justified true belief. Can the problem be resolved? If so, how?

Your response should:
1. Explain Edmund Gettier's counterexamples and their implications
2. Discuss how these cases challenge the classical definition (justified true belief)
3. Explore proposed solutions: adding a "no defeaters" condition, causal theories of knowledge, reliabilism
4. Provide a balanced conclusion acknowledging ongoing philosophical debates""",
        "doc_reference": "Prompt Example 11"
    },

    "prompt_012_cartesian_skepticism": {
        "query": """How does Cartesian skepticism challenge our ability to know anything with certainty? Discuss Descartes' method of doubt and his eventual solution.

Your response should:
1. Outline Descartes' method of doubt and skeptical scenarios (evil demon hypothesis, dreaming argument)
2. Explain how he arrives at the cogito ergo sum ("I think, therefore I am")
3. Describe his attempt to rebuild knowledge from this foundation
4. Critically evaluate whether his solution successfully overcomes skepticism""",
        "doc_reference": "Prompt Example 12"
    },

    "prompt_016_ship_of_theseus": {
        "query": """Explain the Ship of Theseus paradox. What does it reveal about the nature of identity over time?

Analyze responses from both endurantist and perdurantist perspectives:
1. Describe the Ship of Theseus puzzle and its implications for identity persistence
2. ENDURANTISM: Explain how objects persist wholly through time (three-dimensionalism)
3. PERDURANTISM: Explain how objects persist as temporal parts (four-dimensionalism)
4. Analyze which view better addresses the paradox and why""",
        "doc_reference": "Prompt Example 15"
    },

    "prompt_017_modal_realism": {
        "query": """Explain David Lewis's modal realism and compare it with alternative theories like Alvin Plantinga's abstract possible worlds framework.

Your response should:
1. Describe Lewis's "real" possible worlds and his argument for genuine realism
2. Outline main objections to Lewis's view (ontological extravagance, epistemological problems)
3. Discuss Plantinga's abstract modal framework as an alternative
4. Explain why Plantinga's view is seen as more ontologically modest
5. Evaluate the philosophical trade-offs between these positions""",
        "doc_reference": "Prompt Example 16"
    },

    "prompt_019_rawls_nozick": {
        "query": """Compare John Rawls' theory of justice as fairness with Robert Nozick's libertarian critique.

Your response should:
1. Explain Rawls' principles of justice (veil of ignorance, difference principle, fair equality of opportunity)
2. Contrast this with Nozick's entitlement theory and minimal state
3. Use a concrete example to illustrate their differences in distributive justice (e.g., taxation, healthcare, education)
4. Discuss fundamental disagreements about the role of the state""",
        "doc_reference": "Prompt Example 17"
    },

    "prompt_020_social_contract_digital_privacy": {
        "query": """How does social contract theory apply to digital privacy and data governance?

Explain the social contract according to Hobbes, Locke, and Rousseau:
1. Compare Hobbes' pessimistic view of the state of nature with Locke's and Rousseau's more optimistic perspectives
2. Discuss their differing views on the justification for government authority
3. Apply these theories to modern challenges of digital privacy and surveillance
4. Highlight implications for consent, legitimacy, and individual rights in the digital age""",
        "doc_reference": "Prompt Example 18"
    },

    "prompt_022_anarchism_common_good": {
        "query": """Explain the core arguments of political anarchism. How do anarchists justify a rejection of the state, and what alternatives do they propose?

Your response should:
1. Describe anarchist skepticism toward state authority and coercion
2. Discuss key thinkers like Bakunin, Kropotkin, or Proudhon and their arguments
3. Explore proposed alternatives such as voluntary associations, mutual aid, or decentralized governance
4. Address common objections to anarchism (coordination problems, free riders, security)""",
        "doc_reference": "Prompt Example 19"
    },

    "prompt_023_logical_fallacies": {
        "query": """Identify and explain three common logical fallacies: ad hominem, straw man, and slippery slope.

Your response should:
1. Define each fallacy clearly with its logical structure
2. Provide real-world examples from debates, media, or political discourse
3. Explain why each fallacy undermines reasoning and valid argumentation
4. Discuss how to recognize and avoid these fallacies in practice""",
        "doc_reference": "Prompt Example 20"
    },

    "prompt_024_validity_soundness": {
        "query": """Explain the difference between a valid argument and a sound argument. Provide examples of arguments that are valid but unsound.

Your response should:
1. Define validity (logical structure: if premises are true, conclusion must follow)
2. Define soundness (valid argument + actually true premises)
3. Offer clear examples of arguments that are valid but unsound
4. Explain why the distinction matters for evaluating arguments""",
        "doc_reference": "Prompt Example 21"
    },

    "prompt_025_deductive_vs_inductive": {
        "query": """Compare deductive and inductive reasoning, providing examples of each. Discuss the strengths and limitations of both forms of reasoning.

Your response should:
1. DEDUCTIVE REASONING: Define and explain (certainty of conclusions, necessity)
2. INDUCTIVE REASONING: Define and explain (probabilistic conclusions, generalization)
3. Provide concrete examples: syllogisms for deductive, scientific generalizations for inductive
4. Discuss strengths and limitations of each (certainty vs. ampliative inference)
5. Explain when each type of reasoning is appropriate""",
        "doc_reference": "Prompt Example 22"
    },

    "prompt_026_assisted_suicide": {
        "query": """Is physician-assisted suicide ethically permissible?

Discuss arguments for and against:
1. ARGUMENTS FOR: Reference autonomy, dignity, alleviating suffering, quality of life
2. ARGUMENTS AGAINST: Sanctity of life, slippery slope concerns, role of medical professionals
3. DEONTOLOGICAL vs UTILITARIAN perspectives
4. Provide a balanced ethical analysis without asserting a definitive answer""",
        "doc_reference": "Prompt Example 23"
    },

    "prompt_027_crispr_ethics": {
        "query": """Is it ethical to use gene-editing technologies like CRISPR for human enhancement (e.g., increasing intelligence or athleticism)?

Consider arguments from multiple perspectives:
1. AUTONOMY: Individual freedom to enhance oneself or one's children
2. FAIRNESS: Could enhancements exacerbate existing inequalities and create genetic classes?
3. SOCIAL INEQUALITY: Access barriers and distributive justice concerns
4. SAFETY AND UNINTENDED CONSEQUENCES: Long-term risks and effects on gene pool
5. Provide an impartial analysis of the ethical implications""",
        "doc_reference": "Prompt Example 24"
    },

    "prompt_028_animal_research": {
        "query": """Is it ethical to use animals for medical research?

Discuss from multiple philosophical perspectives:
1. UTILITARIAN: Explain arguments that benefits to humans outweigh harm to animals
2. DEONTOLOGICAL: Present concerns about duties to minimize suffering and respect for life
3. RIGHTS-BASED: Explore critiques based on intrinsic moral value of animals
4. Consider the principle of the three Rs (replacement, reduction, refinement)
5. Offer a balanced conclusion acknowledging tensions between positions""",
        "doc_reference": "Prompt Example 25"
    },

    "prompt_029_art_definition": {
        "query": """Discuss the challenges of defining art. Compare and contrast formalist, expressionist, and institutional theories of art.

Your response should:
1. FORMALISM: Explain how art is defined by formal properties (e.g., Clive Bell)
2. EXPRESSIONISM: Discuss how art conveys emotion (e.g., Tolstoy)
3. INSTITUTIONAL THEORY: Outline how art is what institutions recognize as art (e.g., Danto)
4. Provide concrete examples for each theory (e.g., abstract painting, Starry Night, Duchamp's Fountain)
5. Explore whether a single definition of art is possible or desirable""",
        "doc_reference": "Prompt Example 26"
    },

    "prompt_030_beauty_subjective": {
        "query": """Is beauty subjective or objective?

Discuss this question using perspectives from key philosophers:
1. HUME: Summarize his view that beauty is grounded in subjective sentiment but refined by shared taste and ideal critics
2. KANT: Explain his idea of disinterested judgment and universal communicability in aesthetic experience
3. CONTEMPORARY THEORIES: Introduce views exploring cultural relativity, evolutionary aesthetics, or neuroaesthetics
4. Critically evaluate whether a balance between subjectivity and objectivity can be achieved""",
        "doc_reference": "Prompt Example 27"
    },

    "prompt_031_aesthetic_value_society": {
        "query": """What is the role of aesthetic experience in human life and civic society?

Discuss using multiple philosophical perspectives:
1. JOHN DEWEY: Summarize his pragmatist view that aesthetic experience integrates meaning and life through active engagement
2. KANT: Explain his focus on disinterested contemplation and universality in aesthetic experiences
3. CONTEMPORARY VIEWS: Address the psychological and cultural role of art in meaning-making
4. Analyze how aesthetic experiences contribute to human flourishing and civic identity""",
        "doc_reference": "Prompt Example 34"
    },

    "prompt_032_moral_realism": {
        "query": """Can moral realism provide a coherent account of morality?

Compare arguments for moral realism with anti-realist critiques:
1. MORAL REALISM: Define the position (objective moral facts exist) and key arguments (moral convergence, moral experience, companions in guilt)
2. EVOLUTIONARY DEBUNKING: Discuss challenges from evolutionary psychology (moral faculties evolved for fitness, not truth)
3. ERROR THEORY: Outline J.L. Mackie's argument that all moral judgments are systematically false
4. Compare with defenses from Thomas Nagel or Peter Singer
5. Provide balanced evaluation of realism vs. anti-realism""",
        "doc_reference": "Prompt Example 30, 36"
    },

    "prompt_033_moral_motivation": {
        "query": """What motivates moral action?

Compare Humean and Kantian accounts:
1. HUME: Explain his claim that reason is the "slave of the passions" and morality is motivated by desire and sentiment
2. KANT: Present his idea that moral action arises from rational recognition of duty and the categorical imperative
3. MOTIVATIONAL INTERNALISM vs EXTERNALISM: Analyze whether moral judgment necessarily motivates
4. Provide a concrete example of moral motivation and evaluate which theory better explains it""",
        "doc_reference": "Prompt Example 31"
    },

    "prompt_036_purpose_of_philosophy": {
        "query": """What is the purpose of philosophy in contemporary society?

Compare the views of key philosophers on philosophy's role:
1. WITTGENSTEIN: Summarize his view that philosophy clarifies language and dissolves conceptual confusion
2. RICHARD RORTY: Explain his claim that philosophy is about conversation and redescription, not finding objective truths
3. BERTRAND RUSSELL: Contrast with Russell's view of philosophy as pursuit of truth and knowledge
4. Reflect on whether philosophy has practical value, intrinsic value, or both""",
        "doc_reference": "Prompt Example 32"
    },

    "prompt_004_environmental_justice": {
        "query": """Should a developing nation prioritize economic growth over strict carbon reduction targets?

Analyze this dilemma from multiple ethical perspectives:
1. UTILITARIAN VIEW: Discuss the trade-offs between immediate economic benefits and long-term environmental harm
2. JUSTICE PERSPECTIVE: Consider distributive justice, historical responsibility, and intergenerational equity
3. RIGHTS-BASED APPROACH: Address the rights of current populations to development vs. future generations' rights to a livable planet
4. Explore practical compromises: green development, technology transfer, differentiated responsibilities
5. Provide a balanced conclusion recognizing the complexity of the issue""",
        "doc_reference": "Environmental Justice Analysis"
    },

    "prompt_005_medical_autonomy": {
        "query": """During a pandemic, may physicians breach patient confidentiality to alert public health officials about noncompliant individuals?

Analyze this ethical conflict:
1. PATIENT AUTONOMY: Discuss the importance of patient privacy and confidentiality in medical ethics
2. PUBLIC HEALTH: Explain the utilitarian case for protecting community health and preventing disease spread
3. LEGAL AND PROFESSIONAL DUTIES: Consider physicians' conflicting obligations to individual patients vs. society
4. PRECEDENTS AND RISKS: Examine historical cases of mandatory reporting and slippery slope concerns
5. Propose a balanced framework for when breaches may be justified (severity, imminence, proportionality)""",
        "doc_reference": "Medical Ethics Analysis"
    },

    "prompt_006_surveillance_privacy": {
        "query": """Evaluate government deployment of ubiquitous facial recognition for security in dense urban centers.

Analyze from multiple ethical angles:
1. SECURITY ARGUMENT: Present the utilitarian case for enhanced public safety and crime deterrence
2. PRIVACY CONCERNS: Discuss the right to privacy, surveillance state risks, and chilling effects on freedom
3. POWER AND JUSTICE: Address potential for discriminatory enforcement and abuse of authority
4. TECHNOLOGICAL CONSIDERATIONS: Examine accuracy, bias in facial recognition, and transparency issues
5. Compare alternative approaches and propose safeguards (oversight, limitations, accountability)""",
        "doc_reference": "Privacy and Technology Analysis"
    },

    "prompt_009_virtue_ai_design": {
        "query": """How can virtue ethics inform the design of empathetic AI companions for elder care?

Apply virtue ethics to AI design:
1. VIRTUE ETHICS FRAMEWORK: Explain how cultivating virtues (compassion, wisdom, justice) applies to AI development
2. EMPATHY AND CARE: Discuss how AI can embody caring virtues while acknowledging its limitations
3. PRACTICAL DESIGN PRINCIPLES: Address responsiveness, reliability, respect for autonomy, and avoiding manipulation
4. ETHICAL RISKS: Consider potential harms (dependence, deception, substitution for human care)
5. Propose guidelines for virtuous AI design that promotes human flourishing""",
        "doc_reference": "AI Ethics Analysis"
    },

    "prompt_010_autonomous_weapons": {
        "query": """Are autonomous weapons systems ethically permissible?

Examine this question from multiple perspectives:
1. JUST WAR THEORY: Analyze whether autonomous weapons satisfy principles of jus in bello (discrimination, proportionality)
2. ACCOUNTABILITY PROBLEM: Discuss the responsibility gap when machines make lethal decisions
3. DEHUMANIZATION: Consider whether removing humans from the kill chain is morally problematic
4. UTILITARIAN CONSIDERATIONS: Weigh potential benefits (reduced soldier casualties) vs. risks (lowered threshold for war)
5. REGULATORY APPROACHES: Explore proposals for international governance, meaningful human control
6. Provide a balanced assessment of the ethical status of autonomous weapons""",
        "doc_reference": "Military Ethics Analysis"
    },

    "prompt_013_problem_of_induction": {
        "query": """Why does Hume's problem of induction remain unsolved, and what are notable responses?

Provide a comprehensive analysis:
1. HUME'S ARGUMENT: Explain the problem - we cannot justify inductive reasoning without circular reasoning
2. KEY RESPONSES: Discuss major attempts to solve it:
   - Pragmatic justification (it works, even if not provable)
   - Probabilistic approaches (Bayesian epistemology)
   - Naturalistic responses (Quine, evolutionary epistemology)
3. WHY IT REMAINS UNSOLVED: Analyze why each response faces challenges
4. IMPLICATIONS: Discuss the problem's significance for science, knowledge, and rationality
5. Reflect on whether we can live with an unsolved problem of induction""",
        "doc_reference": "Epistemology Analysis"
    },

    "prompt_014_scientific_realism": {
        "query": """Contrast scientific realism with constructive empiricism in interpreting successful scientific theories.

Compare these two positions:
1. SCIENTIFIC REALISM: Define the view that successful theories describe reality accurately, including unobservables
   - Arguments: No-miracles argument, success of science, inference to best explanation
2. CONSTRUCTIVE EMPIRICISM: Explain van Fraassen's view that theories need only be empirically adequate
   - Arguments: Underdetermination, pessimistic meta-induction, observability distinction
3. KEY DEBATES: Discuss disputes over theory choice, explanation, and the status of unobservable entities
4. IMPLICATIONS: Analyze what each view means for scientific practice and progress
5. Provide a balanced assessment of strengths and weaknesses of each position""",
        "doc_reference": "Philosophy of Science Analysis"
    },

    "prompt_015_feminist_epistemology": {
        "query": """Can knowledge claims be value-neutral, or are they shaped by social and political contexts?

Examine this question through feminist epistemology:
1. TRADITIONAL VIEW: Explain the ideal of value-neutral, objective knowledge
2. FEMINIST CRITIQUES: Discuss how standpoint theory, situated knowledge, and epistemic injustice challenge this ideal
   - Standpoint theory: Marginalized perspectives can provide epistemic advantages
   - Situated knowledge: All knowledge is produced from particular social locations
3. EXAMPLES: Illustrate with cases of bias in science, medicine, or social research
4. OBJECTIVITY REVISED: Explore proposals for "strong objectivity" or "contextual objectivity"
5. Reflect on implications for scientific practice and democratic deliberation""",
        "doc_reference": "Feminist Epistemology Analysis"
    },

    "prompt_018_personal_identity_teleportation": {
        "query": """If a teleporter destroys your body and creates an exact duplicate elsewhere, would the duplicate be you?

Analyze using theories of personal identity:
1. PHYSICAL CONTINUITY THEORY: Discuss the view that you are your body - implications for teleportation
2. PSYCHOLOGICAL CONTINUITY THEORY: Explain Locke's view that memory and consciousness determine identity
3. NO-SELF VIEW: Introduce Buddhist or Parfitian perspectives that identity may be an illusion
4. PRACTICAL IMPLICATIONS: Consider what each theory means for survival, moral responsibility, and selfhood
5. Explore whether the question has a definite answer or reveals conceptual confusions about identity""",
        "doc_reference": "Personal Identity Analysis"
    },

    "prompt_021_civil_disobedience": {
        "query": """When is civil disobedience morally justified within a democratic society?

Analyze the ethics of civil disobedience:
1. DEFINITION AND EXAMPLES: Define civil disobedience and provide historical examples (Gandhi, MLK, Thoreau)
2. JUSTIFICATION CONDITIONS: Discuss criteria - unjust laws, exhausted legal remedies, proportionality, nonviolence
3. RAWLS VS. KING: Compare Rawls's liberal theory with King's Letter from Birmingham Jail
4. DEMOCRATIC LEGITIMACY: Address the tension between majority rule and moral conscience
5. CONTEMPORARY APPLICATIONS: Consider climate activism, whistleblowing, or other modern cases
6. Provide a framework for evaluating when civil disobedience is ethically permissible""",
        "doc_reference": "Political Philosophy Analysis"
    },

    "prompt_034_error_theory": {
        "query": """Describe moral error theory and evaluate strategies for living without objective moral facts.

Examine moral error theory comprehensively:
1. ERROR THEORY EXPLAINED: Define Mackie's view that all moral claims are false because objective values don't exist
   - Arguments: Argument from queerness, argument from disagreement
2. IMPLICATIONS: Discuss what error theory means for moral language, motivation, and practice
3. FICTIONALISM: Explain the proposal to treat moral discourse as useful fiction
4. ALTERNATIVES: Consider moral expressivism, constructivism, or naturalistic realism as responses
5. LIVING WITHOUT OBJECTIVE MORALITY: Analyze whether we can maintain moral practices without realism
6. Reflect on whether error theory undermines or can accommodate ordinary moral life""",
        "doc_reference": "Metaethics Analysis"
    },

    "prompt_035_virtue_vs_care": {
        "query": """Compare virtue ethics and care ethics in addressing moral dilemmas involving relationships.

Contrast these two approaches:
1. VIRTUE ETHICS: Explain the Aristotelian focus on character, virtues, and eudaimonia
   - Key virtues: courage, justice, temperance, wisdom
   - Role of practical wisdom (phronesis) in particular situations
2. CARE ETHICS: Discuss the feminist emphasis on relationships, interdependence, and responsiveness
   - Noddings, Gilligan: Care as fundamental moral orientation
   - Attention to vulnerability, context, and emotional engagement
3. SIMILARITIES: Identify common ground - particularism, role of emotion, critique of rule-based ethics
4. DIFFERENCES: Analyze divergences - universal virtues vs. relational context, impartiality vs. partiality
5. CASE STUDY: Apply both frameworks to a relationship dilemma and compare their insights""",
        "doc_reference": "Moral Theory Comparison"
    },

    "prompt_037_philosophy_methodology": {
        "query": """Compare analytic and continental methodologies and the value of methodological pluralism.

Examine philosophical methodologies:
1. ANALYTIC PHILOSOPHY: Characterize its focus on logical analysis, clarity, argument, and scientific methods
   - Key figures: Russell, Frege, Quine, Rawls
   - Methods: Conceptual analysis, formal logic, thought experiments
2. CONTINENTAL PHILOSOPHY: Describe its emphasis on interpretation, historicity, lived experience
   - Key figures: Heidegger, Sartre, Foucault, Derrida
   - Methods: Phenomenology, hermeneutics, critical theory, genealogy
3. STEREOTYPES VS. REALITY: Clarify that the division is often overstated and there are bridges
4. METHODOLOGICAL PLURALISM: Argue for the value of multiple approaches to philosophical problems
5. CASE STUDY: Show how a problem (e.g., freedom, justice) looks different through each lens
6. Reflect on whether philosophy benefits from methodological diversity""",
        "doc_reference": "Methodology Analysis"
    },
}


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON file."""
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Save JSON file with formatting."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def enhance_canned_responses() -> tuple[int, int]:
    """Update canned_responses.json with enhanced queries.

    Returns:
        (updated_count, total_count) tuple
    """
    canned_path = Path("tests/fixtures/canned_responses.json")
    canned_data = load_json(canned_path)

    updated_count = 0
    total_count = 0

    for prompt_id, enhanced_data in ENHANCED_QUERIES.items():
        total_count += 1

        if prompt_id not in canned_data:
            console.print(f"[yellow]⚠ Prompt {prompt_id} not found in canned_responses.json[/yellow]")
            continue

        # Update the query string
        old_query = canned_data[prompt_id]["input"]["query_str"]
        new_query = enhanced_data["query"]

        canned_data[prompt_id]["input"]["query_str"] = new_query
        updated_count += 1

        console.print(f"[green]✓ Enhanced {prompt_id}[/green]")
        console.print(f"  Doc: {enhanced_data['doc_reference']}")
        console.print(f"  Old: {len(old_query)} chars")
        console.print(f"  New: {len(new_query)} chars")
        console.print()

    # Save updated data
    save_json(canned_path, canned_data)

    return updated_count, total_count


def generate_enhancement_report() -> None:
    """Generate a report of enhancements."""

    table = Table(title="Prompt Enhancement Summary")
    table.add_column("Prompt ID", style="cyan")
    table.add_column("Doc Reference", style="yellow")
    table.add_column("Status", style="green")

    canned_path = Path("tests/fixtures/canned_responses.json")
    canned_data = load_json(canned_path)

    for prompt_id, enhanced_data in ENHANCED_QUERIES.items():
        status = "✓ Enhanced" if prompt_id in canned_data else "✗ Not found"
        status_style = "green" if prompt_id in canned_data else "red"

        table.add_row(
            prompt_id,
            enhanced_data["doc_reference"],
            f"[{status_style}]{status}[/{status_style}]"
        )

    console.print(table)
    console.print()
    console.print(f"[bold]Total prompts enhanced: {len(ENHANCED_QUERIES)}[/bold]")


def main():
    console.print("[bold cyan]═══ ENHANCING PROMPTS FROM DOCUMENTATION ═══[/bold cyan]\n")

    # Backup original
    backup_path = Path("tests/fixtures/canned_responses.json.backup")
    original_path = Path("tests/fixtures/canned_responses.json")

    if not backup_path.exists():
        console.print(f"[yellow]Creating backup at {backup_path}...[/yellow]")
        import shutil
        shutil.copy(original_path, backup_path)
        console.print("[green]✓ Backup created[/green]\n")

    # Enhance prompts
    updated, total = enhance_canned_responses()

    console.print(f"\n[bold green]✓ Enhanced {updated}/{total} prompts[/bold green]\n")

    # Generate report
    generate_enhancement_report()

    console.print("\n[bold cyan]Next Steps:[/bold cyan]")
    console.print("1. Review enhanced prompts in tests/fixtures/canned_responses.json")
    console.print("2. Run: python tests/run_live_prompts.py")
    console.print("3. Compare results: python tests/generate_comparison_report.py")
    console.print("4. Analyze improvements: python tests/analyze_prompt_performance.py")
    console.print()
    console.print("[dim]To restore original: cp tests/fixtures/canned_responses.json.backup tests/fixtures/canned_responses.json[/dim]")


if __name__ == "__main__":
    main()
