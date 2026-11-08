import { describe, expect, it } from 'vitest'
import { CATEGORY_ICON, FALLBACK_ICON, ROLE_ICON, TRAIT_ICON, categoryIcon, roleIcon, traitIcon } from './civilianIcons'

// the engine's names (twin/engine/decision/schema.py): every one needs an icon, nothing is drawn as text or emoji
const CATEGORIES = ['home', 'office', 'grocery', 'restaurant', 'cafe', 'school', 'gym', 'clinic', 'pharmacy', 'park', 'bank', 'hospital', 'mall', 'transit_stop', 'worship', 'market']
const ROLES = ['worker', 'student', 'retiree', 'parent', 'freelancer']
const TRAITS = ['urgency', 'risk_aversion', 'sociability', 'routine', 'thrift', 'health_focus', 'curiosity']

describe('civilian icons', () => {
  it('cover every place category, role and trait the engine knows', () => {
    for (const c of CATEGORIES) expect(CATEGORY_ICON[c], c).toBeDefined()
    for (const r of ROLES) expect(ROLE_ICON[r], r).toBeDefined()
    for (const t of TRAITS) expect(TRAIT_ICON[t], t).toBeDefined()
  })

  it('give each place category its own icon', () => {
    expect(new Set(CATEGORIES.map((c) => CATEGORY_ICON[c])).size).toBe(CATEGORIES.length)
  })

  it('fall back to an icon for a name the engine adds later', () => {
    expect(categoryIcon('observatory')).toBe(FALLBACK_ICON)
    expect(roleIcon('astronaut')).toBeDefined()
    expect(traitIcon('luck')).toBeDefined()
  })
})
