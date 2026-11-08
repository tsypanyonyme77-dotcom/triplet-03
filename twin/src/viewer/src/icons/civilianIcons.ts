import {
  Armchair, Baby, BusFront, Briefcase, Car, Church, Coffee, Dumbbell, Eye, GraduationCap, HeartPulse, Hospital,
  House, Landmark, Laptop, MapPin, MapPinned, Pill, PersonStanding, PiggyBank, Repeat, ShieldAlert, ShoppingBag,
  ShoppingBasket, Stethoscope, Store, Timer, Trees, Users, Utensils, type LucideIcon,
} from 'lucide-react'

/** One icon per kind of place (the names are the engine's place categories). */
export const CATEGORY_ICON: Record<string, LucideIcon> = {
  home: House,
  office: Briefcase,
  grocery: ShoppingBasket,
  restaurant: Utensils,
  cafe: Coffee,
  school: GraduationCap,
  gym: Dumbbell,
  clinic: Stethoscope,
  pharmacy: Pill,
  park: Trees,
  bank: Landmark,
  hospital: Hospital,
  mall: ShoppingBag,
  transit_stop: BusFront,
  worship: Church,
  market: Store,
}

/** One icon per role a civilian can have. */
export const ROLE_ICON: Record<string, LucideIcon> = {
  worker: Briefcase,
  student: GraduationCap,
  retiree: Armchair,
  parent: Baby,
  freelancer: Laptop,
}

/** One icon per trait of the decision model. */
export const TRAIT_ICON: Record<string, LucideIcon> = {
  urgency: Timer,
  risk_aversion: ShieldAlert,
  sociability: Users,
  routine: Repeat,
  thrift: PiggyBank,
  health_focus: HeartPulse,
  curiosity: Eye,
}

export const KIND_ICON = { car: Car, pedestrian: PersonStanding } as const

/** Marks on a place label for what it means to the selected person. */
export const ROLE_MARK_ICON = { destination: MapPinned, home: House, duty: Briefcase } as const

export const FALLBACK_ICON: LucideIcon = MapPin

export const categoryIcon = (category: string): LucideIcon => CATEGORY_ICON[category] ?? FALLBACK_ICON
export const roleIcon = (role: string): LucideIcon => ROLE_ICON[role] ?? Users
export const traitIcon = (trait: string): LucideIcon => TRAIT_ICON[trait] ?? Eye
