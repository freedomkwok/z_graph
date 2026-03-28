export default function JsonListEditor({ values = [], onChange, invalidIndexes = [], addLabel }) {
  const invalidSet = new Set(Array.isArray(invalidIndexes) ? invalidIndexes : []);

  const updateItem = (index, nextValue) => {
    const nextValues = [...values];
    nextValues[index] = nextValue;
    onChange(nextValues);
  };

  const removeItem = (index) => {
    onChange(values.filter((_, cursor) => cursor !== index));
  };

  const appendItem = () => {
    onChange([...(Array.isArray(values) ? values : []), "{}"]);
  };

  return (
    <div>
      <div className="ontology-json-list">
        {(Array.isArray(values) ? values : []).map((value, index) => (
          <div className="ontology-json-item" key={`${addLabel}-${index}`}>
            <textarea
              className={`ontology-json-item-input ${invalidSet.has(index) ? "invalid" : ""}`}
              value={String(value ?? "")}
              rows={3}
              onChange={(event) => updateItem(index, event.target.value)}
            />
            <div className="ontology-json-item-actions">
              <button
                className="ontology-json-remove-btn"
                type="button"
                onClick={() => removeItem(index)}
              >
                Remove
              </button>
            </div>
            {invalidSet.has(index) && (
              <p className="ontology-json-item-error">Invalid JSON. Fix this item before confirming.</p>
            )}
          </div>
        ))}
      </div>
      <button className="ontology-json-add-btn" type="button" onClick={appendItem}>
        {addLabel}
      </button>
    </div>
  );
}
