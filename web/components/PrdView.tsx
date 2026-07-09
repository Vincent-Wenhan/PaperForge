"use client";

interface PrdViewProps {
  prd: any;
}

export function PrdView({ prd }: PrdViewProps) {
  if (!prd) {
    return <div className="text-muted-foreground">No PRD</div>;
  }

  const FeatureList = ({
    title,
    features,
  }: {
    title: string;
    features?: any[];
  }) => {
    if (!features || features.length === 0) return null;
    return (
      <div>
        <h4 className="text-xs font-semibold uppercase text-muted-foreground">
          {title}
        </h4>
        <ul className="text-sm list-disc list-inside space-y-1">
          {features.map((f: any, i: number) => (
            <li key={i}>
              <span className="font-medium">{f.name}</span>
              {f.description && `: ${f.description}`}
            </li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {prd.product_name && (
        <h3 className="font-semibold text-lg">{prd.product_name}</h3>
      )}
      {prd.one_liner && (
        <p className="text-sm text-muted-foreground">{prd.one_liner}</p>
      )}
      {prd.value_proposition && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Value Proposition
          </h4>
          <p className="text-sm">{prd.value_proposition}</p>
        </div>
      )}
      <FeatureList title="Must Have" features={prd.must_have} />
      <FeatureList title="Should Have" features={prd.should_have} />
      <FeatureList title="Could Have" features={prd.could_have} />
    </div>
  );
}
