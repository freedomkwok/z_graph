## Requirement Context

{{context_requirement}}

## Skill Content
{{combined_text}}

## Additional Notes
{{additional_context}}

## Output Constraints
- Minimum entity types (nodes): {{minimum_nodes}}
- Minimum relationship types (edges): {{minimum_edges}}

Please design suitable entity types and relationship types based on the above skill content.

**Rules that must be followed**:
- Use English PascalCase for entity name
- Use English UPPER_SNAKE_CASE for `relationship_types`
1. You must output at least {{minimum_nodes}} entity types.
2. Include `Skill` (skill fallback) and `RegistryObject` (registry/supporting fallback) in entity types.
3. Keep the majority of entity types specific to the provided skill content.
4. You must output at least {{minimum_edges}} relationship types.
5. All entity types must be valid skill-registry objects that help define, retrieve, constrain, route, sequence, or execute skills, not generic abstract concepts with no registry use.
6. Attribute names cannot use reserved words such as `name`, `uuid`, `group_id`, `created_at`, `summary`; use alternatives like `skill_id`, `title`, `description`, `signal_text`, `scenario_label`, or `constraint_text`.
7. Relationship types should prioritize skill-registry structure, including applicability, exclusion, triggering, requirement, dependency, composition, categorization, or execution ordering where supported by the content.
8. If the content contains sequencing, prerequisite, or multi-skill workflow logic, reflect that in the entity and relationship design.