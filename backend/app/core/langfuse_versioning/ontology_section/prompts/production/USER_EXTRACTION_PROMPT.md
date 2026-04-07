## Requirement Context

{{context_requirement}}

## Document Content

{{combined_text}}

## Additional Notes

{{additional_context}}

## Output Constraints

- Minimum entity types (nodes): {{minimum_nodes}}
- Minimum relationship types (edges): {{minimum_edges}}

Please design suitable entity types and relationship types based on the above content.

**Rules that must be followed**:
1. You must output at least {{minimum_nodes}} entity types.
2. Include Person (individual fallback) and Organization (organization fallback) in entity types.
3. Keep the majority of entity types specific to the uploaded content.
4. You must output at least {{minimum_edges}} relationship types.
5. All entity types must be real-world actors that can speak publicly, not abstract concepts.
6. Attribute names cannot use reserved words such as name, uuid, group_id; use alternatives like full_name and org_name.

