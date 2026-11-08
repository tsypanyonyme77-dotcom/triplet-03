import { ActionButton } from '../components/ActionButton'
import { setAuto } from './brainApi'

export function ModeSwitch({ auto }: { auto: boolean }) {
  return (
    <p>
      Decisions come from <strong>{auto ? 'the auto rule' : 'you, the operator'}</strong>.{' '}
      <ActionButton
        label={auto ? 'Decide by hand' : 'Let the auto rule decide'}
        run={() => setAuto(!auto).then(() => 'changed')}
      />
    </p>
  )
}
