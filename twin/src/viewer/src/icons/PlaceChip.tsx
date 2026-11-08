import { colorOf } from '../scene/placeLabels'
import { categoryIcon } from './civilianIcons'

/** A place as an icon for its kind and its name. */
export function PlaceChip({ category, name, size = 14 }: { category: string; name: string; size?: number }) {
  const Icon = categoryIcon(category)
  return (
    <span className="place-chip" title={`${name} (${category.replace(/_/g, ' ')})`}>
      <Icon size={size} color={colorOf(category)} />
      <span>{name}</span>
    </span>
  )
}
