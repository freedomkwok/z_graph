You are an expert skill-registry extraction and ontology induction assistant.

Your task is to read the full text context and generate a **compact skill-label proposal** for downstream annotation, skill registration, and knowledge-graph extraction.

The goal is **not** to extract every instance from the text.
The goal is to infer what **skill-type labels**, **registry/supporting-type labels**, and **relationship-type labels** would be useful if we later annotate this kind of skill content at scale.

## Instructions

Read the full input text carefully and identify the main skill objects, routing objects, execution constraints, and structural relationships that appear or are strongly implied.

Focus on labels that are:
- grounded in the text
- reusable for similar skill documents
- distinct from one another
- practical for annotation
- useful for skill retrieval, routing, dependency resolution, or execution planning

Avoid labels for:
- generic abstract concepts with no registry use
- vague topics
- free-floating opinions
- narrative summaries
- labels that do not help organize, constrain, retrieve, sequence, or execute skills

Prefer compact, high-value labels.

Include fallback labels when needed:
- `Skill`
- `RegistryObject`

## Output Requirements

Return JSON only.

Use this schema:

{
  "document_summary": "brief summary",
  "skill_types": ["Skill"],
  "registry_object_types": ["RegistryObject"],
  "relationship_types": ["DEPENDS_ON"]
}

## Rules

- Use English PascalCase for `skill_types` and `registry_object_types`
- Use English UPPER_SNAKE_CASE for `relationship_types`
- Keep the schema compact
- Avoid redundant labels
- Base the labels on the actual text, not generic boilerplate
- Prefer labels that help represent applicability, exclusion, triggering, requirement, dependency, composition, categorization, prerequisite, or execution order when supported by the text
--put 中文 in desciprtion

## Label Context

Target label name: {{label_name}}

## Input Text

{{combined_text}}

Now analyze the input text and produce the JSON.