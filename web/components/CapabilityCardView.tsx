"use client";

interface CapabilityCardViewProps {
  card: any;
}

export function CapabilityCardView({ card }: CapabilityCardViewProps) {
  if (!card) {
    return <div className="text-muted-foreground">No capability card</div>;
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="font-semibold text-lg">{card.title}</h3>
        {card.authors && card.authors.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {card.authors.join(", ")}
            {card.year ? ` (${card.year})` : ""}
          </p>
        )}
      </div>

      {card.problem && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Problem
          </h4>
          <p className="text-sm">{card.problem}</p>
        </div>
      )}

      {card.method && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Method
          </h4>
          <p className="text-sm">{card.method}</p>
        </div>
      )}

      {card.key_innovations && card.key_innovations.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Key Innovations
          </h4>
          <ul className="text-sm list-disc list-inside">
            {card.key_innovations.map((item: string, i: number) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {card.reusable_components && card.reusable_components.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Reusable Components
          </h4>
          <ul className="text-sm list-disc list-inside">
            {card.reusable_components.map((item: string, i: number) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {card.product_hints && card.product_hints.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Product Hints
          </h4>
          <ul className="text-sm list-disc list-inside">
            {card.product_hints.map((item: string, i: number) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {card.parse_coverage && (
        <div className="mt-2">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Understanding
          </h4>
          {card.parse_coverage.complete ? (
            <p className="text-sm">
              Parsed {card.parse_coverage.total_pages} / {card.parse_coverage.total_pages} pages · Full understanding
            </p>
          ) : (
            <p className="text-sm text-amber-700 dark:text-amber-300">
              Parsed {card.parse_coverage.processed_pages?.length ?? 0} / {card.parse_coverage.total_pages} pages · Partial understanding
            </p>
          )}
        </div>
      )}
    </div>
  );
}
