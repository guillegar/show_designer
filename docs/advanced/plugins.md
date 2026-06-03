# Creating Plugins 🔌

Add custom effects to Show Designer Pro without modifying core code.

## Quick Start

Create a file `plugins/effects/my_effect.py`:

```python
from src.core.effects_engine import Effect, EffectScope, EffectGeometry, EffectSymmetry
import numpy as np

class RainbowPulse(Effect):
    """Pulsing rainbow effect."""
    
    name = "rainbow_pulse"
    family = "custom"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Rainbow colors pulsing in intensity"
    
    def render(self, elapsed_time, bars_state, audio_context, **params):
        """Calculate RGB values for this frame."""
        
        # Get parameters with defaults
        speed = params.get('speed', 1.0)
        intensity = params.get('intensity', 1.0)
        
        # Calculate hue based on time
        elapsed_sec = elapsed_time / 1000.0
        hue = (elapsed_sec * speed) % 360
        
        # Create rainbow colors
        num_leds = bars_state[0].shape[1]
        result = bars_state.copy()
        
        for led_idx in range(num_leds):
            # Shift hue per LED for rainbow effect
            led_hue = (hue + led_idx * 360 / num_leds) % 360
            
            # Convert HSV to RGB
            rgb = self._hsv_to_rgb(led_hue, 1.0, intensity)
            
            # Apply to all bars
            result[:, led_idx] = np.array(rgb, dtype=np.uint8)
        
        return result
    
    @staticmethod
    def _hsv_to_rgb(h, s, v):
        """Convert HSV to RGB."""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h / 360, s, v)
        return [int(r * 255), int(g * 255), int(b * 255)]

# Register the plugin
PLUGIN_EFFECTS = {
    1000: RainbowPulse(),  # IDs >= 1000 are for plugins
}
```

**Restart Show Designer Pro**, and your effect appears in the browser under "custom" family!

## Effect Parameters

Effects can accept user-configurable parameters:

```python
class MyEffect(Effect):
    name = "my_effect"
    scope = EffectScope.ALL_BARS
    
    # Define parameters (shown in UI)
    parameters = {
        'speed': {'min': 0.1, 'max': 2.0, 'default': 1.0},
        'intensity': {'min': 0, 'max': 1, 'default': 0.8},
        'color': {'type': 'color', 'default': '#FF0000'},
    }
    
    def render(self, elapsed_time, bars_state, audio_context, **params):
        speed = params.get('speed', 1.0)
        intensity = params.get('intensity', 0.8)
        # ... use parameters ...
        return bars_state
```

## Accessing Audio Context

Make your effect reactive to music:

```python
class AudioReactiveEffect(Effect):
    name = "audio_reactive"
    
    def render(self, elapsed_time, bars_state, audio_context, **params):
        # Available audio features:
        energy = audio_context.energy  # 0-1, current loudness
        beat_phase = audio_context.beat_phase  # 0-1, progress in beat
        tempo = audio_context.tempo  # BPM
        section_type = audio_context.section_type  # 'verse', 'chorus', etc.
        
        # Example: Flash on beat
        if beat_phase < 0.1:  # Flash in first 10% of beat
            return bars_state * 2  # Brighten
        else:
            return bars_state * 0.5  # Dim
```

## Channel Effects (for DMX)

Create effects for moving heads, wash fixtures, etc.:

```python
from src.core.channel_effects import ChannelEffect, ChannelEffectScope

class PosCircle(ChannelEffect):
    """Move fixture in a circle."""
    
    name = "pos_circle"
    category = "position"
    scope = ChannelEffectScope.SINGLE_FIXTURE
    
    required_channels = ["pan", "tilt"]  # Fixture must have these
    
    parameters = {
        'radius': {'min': 0, 'max': 1, 'default': 0.5},
        'speed': {'min': 0.1, 'max': 2, 'default': 1.0},
    }
    
    def render(self, elapsed_time, fixture, audio_context, **params):
        """Return dict of {channel_name: value}."""
        
        import math
        
        elapsed_sec = elapsed_time / 1000.0
        speed = params.get('speed', 1.0)
        radius = params.get('radius', 0.5)
        
        # Calculate circle position
        angle = (elapsed_sec * speed * 2 * math.pi) % (2 * math.pi)
        pan = int(128 + 127 * radius * math.cos(angle))
        tilt = int(128 + 127 * radius * math.sin(angle))
        
        return {
            'pan': pan,
            'tilt': tilt,
        }

PLUGIN_EFFECTS = {
    1000: PosCircle(),
}
```

## Plugin Structure

```
plugins/
├── effects/
│   ├── my_effect.py        ← Your effect
│   ├── my_channel_effect.py
│   └── example_plugin.py   ← Reference implementation
└── __init__.py
```

## Best Practices

1. **Unique IDs**: Use IDs >= 1000 for plugins (0-999 reserved for builtins)
2. **Docstrings**: Every class should have a doc string
3. **Parameters**: Make effects parameterizable, not hardcoded
4. **Performance**: Avoid heavy computation in `render()` (30 FPS constraint)
5. **Testing**: Write tests in `tests/test_plugin_system.py`

## Testing Your Plugin

```python
# tests/test_my_plugin.py

import pytest
from plugins.effects.my_effect import RainbowPulse

def test_rainbow_pulse_renders():
    import numpy as np
    effect = RainbowPulse()
    
    bars_state = np.zeros((10, 93, 3), dtype=np.uint8)
    result = effect.render(
        elapsed_time=500,
        bars_state=bars_state,
        audio_context=None,
        speed=1.0,
        intensity=0.8
    )
    
    assert result.shape == bars_state.shape
    assert result.dtype == np.uint8
```

## Sharing Your Plugin

1. Fork [Show Designer Pro](https://github.com/guillegar/show_designer)
2. Add your plugin to `plugins/effects/`
3. Open a PR with tests and documentation
4. We'll merge and credit you!

## Full Example: Audio-Reactive Strobe

```python
from src.core.effects_engine import Effect, EffectScope

class AudioStrobe(Effect):
    """Strobe intensity based on audio beats."""
    
    name = "audio_strobe"
    family = "strobes"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    
    parameters = {
        'sensitivity': {'min': 0.1, 'max': 1.0, 'default': 0.7},
    }
    
    def render(self, elapsed_time, bars_state, audio_context, **params):
        if audio_context is None:
            return bars_state
        
        sensitivity = params.get('sensitivity', 0.7)
        energy = audio_context.energy
        
        # Strobe brightness from audio energy
        brightness = int(energy * sensitivity * 255)
        
        return bars_state * (brightness / 255) if brightness > 0 else bars_state * 0.1

PLUGIN_EFFECTS = {
    1000: AudioStrobe(),
}
```

---

## Troubleshooting

**Q: My effect doesn't appear in the browser**
A: Check:
- File is in `plugins/effects/` directory
- Has `PLUGIN_EFFECTS` dict at module level
- No syntax errors: run `python plugins/effects/my_effect.py`

**Q: My effect renders black**
A: Ensure you return np.uint8 arrays with values 0-255

**Q: Performance is slow**
A: Profile with `cProfile` to find bottlenecks. Avoid:
- List comprehensions over huge arrays
- Importing inside `render()` method
- Heavy trigonometry (pre-calculate if possible)

---

## Resources

- [Effect Base Classes](https://github.com/guillegar/show_designer/blob/master/src/core/effects_engine.py)
- [Example Plugins](https://github.com/guillegar/show_designer/tree/master/plugins/effects)
- [Test Examples](https://github.com/guillegar/show_designer/blob/master/tests/test_plugin_system.py)

---

**Have questions?** Open a [GitHub Discussion](https://github.com/guillegar/show_designer/discussions)!
