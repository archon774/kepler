# Optical observations in the Skynet monorepo

**Repository snapshot:** 2026-09-24. **Scope:** observer-authored optical science observations in the current Skynet platform. This is a code-backed working reference, not a promise that every stored option is enforced by the scheduler or that every provisioned telescope is online tonight.

## Executive map

An observation is a funded, scheduled program with one target, one shared optical-imaging configuration, and one or more ordered optical-imaging requests. A request specifies filters, exposure depth, temporal samples, and camera preferences. The configuration specifies pointing, framing, sky limits, and exposure models. The observation itself specifies ownership, grants, priority, visits, cadence, grouping, instrument selection, and visibility. The scheduler materializes result cells and assigns telescope-specific tasks; SkyNode executes those tasks and produces assets.

```text
Observation (name, funding, schedule, access, visibility)
├── Target (name, position, pointing offset)
│   └── Fixed coordinates | catalog object | orbital elements | ephemeral position
├── OpticalImagingConfiguration (shared by all optical requests)
│   ├── tracking / recentering / dither / mosaic / readout sampling
│   ├── elevation / Sun / Moon constraints
│   └── brightness model / saturation model
├── OpticalImagingRequest 0..N (ordered)
│   ├── filters and exposure-sizing mode
│   ├── sample count, active flag, coadding, registration
│   └── camera/readout preferences
└── observing grants → eligible telescope queues → compatible instruments
    └── results → telescope-specific tasks → exposures/assets
```

The public create route is `POST /v1/users/{slug}/observations` or `POST /v1/organizations/{slug}/observations`. The React `/observe` editor instead holds a versioned `ObservationSpec` in client state and calls `POST /v1/observation-specs:publish` at the final step. Both paths create an active observation in one transaction; a saved editor draft is a saved spec, not a schedulable observation. The relevant implementations are [entity observation creation](../../../apps/public-api/public_api/routers/entities/observations.py), [spec endpoints](../../../apps/public-api/public_api/routers/observation_specs.py), [spec materialization](../../../packages/py/skynet-db/skynet_db/specs.py), and [React review/publish](../../../apps/website-react/app/routes/observe/edit-review.tsx). The observer-facing sequence is accounts → target → requests → configuration → review in [the editor overview](../../skynet_docs/observers/editor/index.md).

### How to create one

1. Select the owner entity and at least one `observingGrantId` that it may spend. Grants lead through observing accounts and queue access to eligible telescopes; they do not name a telescope directly. Discover accessible telescopes with `/v1/me/observing-access/telescopes`, grants with `/v1/observing-grants?telescopeId=…`, and an imager/filter set from the telescope detail endpoint. See [the API guide](../../skynet_docs/developers/guides/creating-observations.md) and [grant validation](../../../apps/public-api/public_api/auth.py).
2. Provide a named target with a resolvable position. A fixed equatorial target uses `positionType: "fixed"` and `coordinateType: "equatorial"`; catalog search can supply `catalogObjectId` for a moving or named object. Set `trackingMode: "sidereal"` for a stationary field or `"target"` for a moving target.
3. Add an `opticalImagingConfiguration` and at least one request with `requestType: "optical_imaging"`. Give each request an `order`, filters and **one intended exposure-sizing mode**. The shared configuration can be tuned for observability, FOV/tiling, dithering, pointing, and brightness.
4. Optionally restrict the instrument pool with observation-level `instrumentMode` (`none`, `include`, `exclude`) plus `instrumentIds`. The union of grants establishes the reachable queue set; the mode/list narrows its instruments. Omit the restriction if any compatible funded imager is acceptable.
5. Submit camelCase JSON and retain the returned observation `id` or `uid`. There is no idempotency key. `:validate` checks a portable spec; `:plan` previews optical tiling/exposure against one instrument without persisting; `:publish` turns a spec plus owner/grants into an observation. The direct entity POST uses `ObservationCreate` and an allow-list. See [API conventions](../../skynet_docs/developers/getting-started/conventions.md) and [spec endpoint implementation](../../../apps/public-api/public_api/routers/observation_specs.py).

For example, this is the shape of a fixed-position, fixed-time observation; replace the sample IDs with IDs fetched for the intended telescope and grant:

```json
{
  "name": "Example V-band field",
  "target": {
    "name": "Example field",
    "position": {
      "positionType": "fixed",
      "coordinates": { "coordinateType": "equatorial", "raDeg": 49.575, "decDeg": -66.5 }
    }
  },
  "opticalImagingConfiguration": {
    "trackingMode": "sidereal",
    "ditherStrategy": "none",
    "temporalOffsetSec": 0,
    "maxTiles": 1,
    "tileOverlap": 0
  },
  "requests": [{
    "requestType": "optical_imaging",
    "order": 0,
    "sampleCount": 1,
    "filterSpecifierIds": ["V"],
    "exposureTimeSec": 30
  }],
  "observingGrantIds": [123],
  "instrumentMode": "include",
  "instrumentIds": [456]
}
```

`123` and `456` are placeholders. A filter ID is a canonical filter or filter-group specifier, not the integer position of a wheel slot. A filter group's members are alternatives for compatibility; a request's filter specifiers combine via a Cartesian product. Confirm the actual filter ID and instrument compatibility before posting. See [filter specifiers](../../../packages/py/skynet-sdk/skynet_sdk/schemas/filter_specifier/base.py) and [request resolution](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py).

## Where the authoritative fields live

| Layer | Source of field names | Persistence/behavior | Why read it |
|---|---|---|---|
| Direct create | [ObservationCreate](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/create.py) | [entity POST allow-list](../../../apps/public-api/public_api/routers/entities/observations.py) | What a client may submit versus typed but ignored lifecycle fields. |
| Portable spec | [ObservationSpec](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation_spec.py) | [build/update/serialize](../../../packages/py/skynet-db/skynet_db/specs.py) | What editor, templates, export and alerts reuse; excludes owner, grants, visibility, and database IDs. |
| Target | [TargetCreate](../../../packages/py/skynet-sdk/skynet_sdk/schemas/target/create.py), [positions](../../../packages/py/skynet-sdk/skynet_sdk/schemas/target_position/create.py), [coordinates](../../../packages/py/skynet-sdk/skynet_sdk/schemas/coordinates/create.py) | [target ORM](../../../packages/py/skynet-db/skynet_db/models/observations/targets.py) | Pointing and coordinate inputs. |
| Shared optical configuration | [OpticalImagingConfiguration schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/base.py) | [optical configuration ORM](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py) | One record per observation; all optical requests share it. |
| Optical request | [OpticalImagingRequestCreate](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation_request/create.py) | [request ORM and exposure code](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py) | Per-pass exposure, filters and camera choices. |
| Repetition/limits | [scheduling enums](../../../packages/py/skynet-sdk/skynet_sdk/enums.py), [normalizer](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/scheduling_policy.py) | [observation ORM](../../../packages/py/skynet-db/skynet_db/models/observations/observations.py), [scheduler cadence](../../../services/scheduler/preprocessing/policies/cadence_plan.py) | Defaults, cross-field invariants, actual scheduling. |
| Render preferences | [RenderSettings](../../../packages/py/skynet-sdk/skynet_sdk/schemas/render_settings.py) | `observations.render_settings` JSONB in [observation ORM](../../../packages/py/skynet-db/skynet_db/models/observations/observations.py) | Image presentation, not acquisition. |

Names below use **Python/ORM snake_case** because that is how the implementation identifies fields. The JSON **field name** is camelCase: for example `target_full_well_fraction` → `targetFullWellFraction`. Enum **values** are not camel-cased: the `requestType` discriminator is `optical_imaging`. `SkynetBaseModel` supplies the field alias conversion. The Python SDK should serialize with `model_dump(..., by_alias=True, exclude_unset=True)`; otherwise defaulted or old fields can be posted unintentionally.

## Every top-level observation creation parameter

Source: [create schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/create.py), [API allow-list](../../../apps/public-api/public_api/routers/entities/observations.py), [database columns](../../../packages/py/skynet-db/skynet_db/models/observations/observations.py). Defaults here are schema defaults unless stated otherwise. `ObservationSpec` includes the portable science/scheduling subset; its instrument list uses stable `instrument_uids` instead of the direct create request's integer `instrument_ids`.

| Field | Default / values | Meaning and implementation notes |
|---|---|---|
| `name` | Required string; DB `String(100)` | Display name. Spec allows it to be omitted so a template/alert can fill it; a usable new observation needs one. |
| `target` | Optional in schema | Inline `TargetCreate`; required in normal editor flow. A template or alert may supply/override it later. |
| `requests` | Optional list in schema | Ordered discriminated request union. Ordinary optical observing uses `request_type=optical_imaging`; calibration kinds are scheduler-generated. The editor requires at least one. |
| `optical_imaging_configuration` | Optional in schema | Shared optical settings; needed for actual optical task planning. Other configuration families are `radio_tracking_configuration` and `radio_mapping_configuration`, outside this report. |
| `observing_grant_ids` | No default grant | Funding and queue access; direct create route rejects an empty list and validates same owner, active grants, and caller rights. The spec omits it; publish supplies it as a sidecar. |
| `instrument_mode` | `none`; `include`, `exclude` | Observation-wide instrument filter. `none` means any compatible instrument reachable through grants. `include`/`exclude` interprets `instrument_ids`; the spec uses `instrument_uids`. |
| `instrument_ids` | `null` | Integer instrument list on direct create/publish. A telescope is reached by its optical imager ID, not by a `telescopeId` field on the observation. |
| `priority` | `0` | Relative ranking inside an eligible queue and its policy; not an absolute rank across the network. |
| `interrupt_lower_priority` | `false` | Request preemption of a lower-priority active observation where the queue/account permits interruption. |
| `start_after` | `null` | Earliest UTC instant at which work may become eligible. |
| `cancel_on` | `null` | Expiration instant; pending work is canceled once the bound applies. |
| `epoch_count` | `1`; `0` means indefinite | Number of full visits to the target. Each visit traverses all active requests/samples. |
| `cohesion_level` | `epoch` | Largest unit that must stay together: `frame`, `sample`, `segment`, `epoch`, `observation`. `frame` currently groups like `sample` in the scheduler; frames are not independently scheduled. |
| `sample_ordering` | `request_major` | `request_major` completes a request's samples before the next request; `sample_major` cycles across requests at each sample index. This also defines what a `segment` is. |
| `cadence_kind` | `asap` | `asap`, `min_gap`, `period`, `calendar`. See the dependent fields and enforcement caveats below. |
| `cadence_level` | `null` for `asap` | Rung whose repeated units are spaced. Required for other cadence kinds. |
| `cadence_gap_sec` | `null` | Minimum end-to-start gap for `min_gap`. |
| `cadence_period_sec` | `null` | Start-to-start period for `period`, anchored to the first unit. |
| `cadence_calendar_unit` | `null`; `night`, `day` | Calendar period for `calendar`, at the assigned telescope's site. |
| `copies_mode` | `single`; `all_eligible`, `count` | Number of independent datasets/instrument copies. `count` requires `copies_count ≥ 1`; `all_eligible` covers each eligible instrument. |
| `copies_count` | `null` | Fixed requested count for `copies_mode=count`; cleared for other modes. |
| `coordination_kind` | `null` for `single`; otherwise defaults to `independent` | `independent` or `synchronized` start intent for multiple copies. Synchronized execution is currently model-only; do not promise simultaneous starts. |
| `coordination_start_tolerance_sec` | `null`; normalized to `0` for synchronized | Allowed difference between synchronized copy starts, recorded for the planned policy. |
| `affinity_migrate_at` | `observation` | Finest rung at which a different eligible instrument may take later work. `observation` binds one instrument for the whole observation. Finer migration is not fully enforced. |
| `affinity_handoff_after_sec` | `null` for observation-level affinity; otherwise `600` | Idle interval before a stalled unit may be released for reassignment. Stored/normalized; migration handling is still staged. |
| `interrupt_recovery` | `resume`; `restart_unit` | Requested behavior after an interruption. `resume` matches current execution; treat `restart_unit` as policy intent until verified for a specific runtime. |
| `is_public` | `false` | Visibility of the observation. The portable spec omits it; the publish sidecar can set it. |
| `render_settings` | `null` | Optional display stretch/palette; see the render table. |

The create schema also declares `status`, `is_deleted`, `owner_id`, `completed_on`, `last_activity_on`, and `progress_fraction`, but the direct POST allow-list deliberately excludes them. The server derives the owner from the URL, takes the creator from the authenticated user, starts the observation active, and manages lifecycle/progress. `kind` appears in the route allow-list but is not a field of the current `ObservationCreate` schema; do not send it. `id`, `uid`, `created_on`, `updated_on`, `current_epoch`, `observability_last_updated_on`, `tasks_last_materialized_on`, cover IDs, and task/result IDs are stored or returned state, not observer submission parameters.

### Scheduling rules and what runs

The fine-to-coarse ladder is `frame < sample < segment < epoch < observation`. A **sample** is one request result at the requested depth, potentially multiple camera frames; a **segment** is a request's full sample run under `request_major`, or one cross-request sample round under `sample_major`. The canonical result leaf is `(observation, request, epoch, sample, copy)`; an execution task is a telescope/instrument attempt for that result. Tiling and coadding can multiply actual exposures. See [result materialization](../../../services/observation_result_materializer/main.py), [task scheduler](../../../services/cp_sat_task_scheduler/main.py), and [scheduling guide](../../skynet_docs/observers/editor/scheduling.md).

The [normalizer](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/scheduling_policy.py) clears irrelevant dependent fields and checks `cohesion_level <= cadence_level` (when cadence is not `asap`) and `cohesion_level <= affinity_migrate_at`; [database CHECKs](../../../packages/py/skynet-db/skynet_db/models/observations/observations.py) backstop these. The scheduler groups `frame` at the sample level. Epoch-level `min_gap` and `period` floors have implementation in [cadence planning](../../../services/scheduler/preprocessing/policies/cadence_plan.py); cadence finer than an epoch, synchronized copies, and fine-grained affinity/handoff are not established as fully enforced by the code inspected here. `calendar` is handled at the telescope/site stage. The public scheduling prose that says `min_gap` and `period` are only recorded is too broad for the current epoch-level implementation.

## Target and position parameters

Source: [target create schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/target/create.py), [position variants](../../../packages/py/skynet-sdk/skynet_sdk/schemas/target_position/create.py), [coordinate variants](../../../packages/py/skynet-sdk/skynet_sdk/schemas/coordinates/create.py), [target ORM](../../../packages/py/skynet-db/skynet_db/models/observations/targets.py).

| Field | Meaning |
|---|---|
| `target.name` | Required target label. |
| `target.position` | One polymorphic pointing source, selected by `position_type`. Required by the editor's publish checklist. |
| `target.position_offset_x_deg`, `position_offset_y_deg` | Persistent east/north tangent-plane pointing trim in degrees; defaults `0`. It is applied before tile and dither offsets. |
| `target.position_offset_frame` | Defaults `icrs_tangent`; also `gcrs_tangent`, `altaz_tangent`, `body_fixed`. `body_fixed` is presently valid for the Moon. |
| `target.position_offset_reference_time` | Optional epoch for frame-dependent offset; `null` evaluates at sample time. |
| `target.status`, `target.is_deleted` | Inherited create-schema lifecycle fields, default active/false; not normal science parameters. Leave unset. |

Position variants:

| `position_type` | Additional fields | Use |
|---|---|---|
| `fixed` | `coordinates` | Fixed sky/location coordinate. This is the usual DSO/star/field path. |
| `catalog` | `catalog_object_id` | Pin an object resolved by catalog search; can supply moving-body ephemerides. |
| `orbital` | `orbit_type` (`barycentric`/`geocentric`), `epoch_jyear`, `semilatus_rectum_au`, `eccentricity`, `inclination_deg`, `longitude_of_ascending_node_deg`, `argument_of_perihelion_deg`, `mean_anomaly_deg` | Keplerian orbital position, usually a small body. |
| `ephemeral` | Only discriminator in `EphemeralPositionCreate` | Time-varying position whose ephemeris is attached/resolved elsewhere; the bare create shape provides no ephemeris rows. Prefer a resolved catalog object for ordinary API creation. |

`fixed.coordinates` accepts one coordinate discriminator and a nullable `epoch` timestamp. These are the complete create-shape fields; proper-motion and velocity values default to zero where shown in the schema.

| `coordinate_type` | Required coordinates | Optional fields and units |
|---|---|---|
| `equatorial` | `ra_deg`, `dec_deg` | `distance_pc`; `pm_ra_mas_per_year` (RA × cos Dec), `pm_dec_mas_per_year`; `radial_velocity_km_per_sec`. RA/Dec are ICRS degrees. |
| `ecliptic` | `lon_deg`, `lat_deg` | `type`: geocentric/heliocentric/barycentric × mean/true (default `geocentric_true`); `distance_au`; `pm_lon_mas_per_year`, `pm_lat_mas_per_year`; `radial_velocity_km_per_sec`; `equinox_jyear` (default 2000). |
| `galactic` | `lon_deg`, `lat_deg` | `distance_pc`; `pm_lon_mas_per_year`, `pm_lat_mas_per_year`; `radial_velocity_km_per_sec`. |
| `horizontal` | `az_deg`, `alt_deg` | `pm_az_arcsec_per_sec`, `pm_alt_arcsec_per_sec`. Site/time dependent; avoid for portable multi-site plans. |
| `topocentric` | `ha_deg`, `dec_deg` | `pm_ha_arcsec_per_sec`, `pm_dec_arcsec_per_sec`; `refraction` (default false). Site/time dependent. |

Current target create schema has **no** `description`, `brightness_model`, `saturation_model`, temporal component, or spectral component field. Older [target editor prose](../../skynet_docs/observers/editor/02-target.md) still describes those as Target fields. The live optical schema puts the brightness and saturation models on `optical_imaging_configuration`; adding them to `target` is not the current typed create contract. Some readback endpoints still return `target.position: null`; use the submitted spec/target record or the returned observation ID for follow-up rather than assuming that response embeds the position.

## Optical imaging configuration: every field

One [schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/base.py) is attached to the observation and one [ORM row](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py) is stored in `optical_imaging_observations` (`observation_id` unique). Every optical request on the observation shares it. The schema requires `tracking_mode`, `dither_strategy`, `temporal_offset_sec`, `max_tiles`, and `tile_overlap` in a direct create body even though the ORM has defaults for some of them.

| Field | Units/default | What it does |
|---|---|---|
| `tracking_mode` | Required: `sidereal` or `target` | Star-rate tracking versus target-rate tracking for a moving object. |
| `repointing_strategy` | `fov_threshold`; or `lock` | For a target drifting relative to the selected tracking rate, recenter after a FOV threshold or lock the first exposure coordinate. It is effectively irrelevant for a fixed sidereal target. |
| `recentering_threshold` | ORM default `50` percent of sensor half-size | Displacement at which `fov_threshold` repoints. `50` means the target drifts halfway from center toward an edge. |
| `temporal_offset_sec` | Required; ORM default `0` seconds | Evaluate the target position at a time offset from the nominal pointing time; predictive or delayed pointing. |
| `field_locked_on` | `null` | Timestamp of the locked initial field for `lock`. Runtime state; do not normally author it. |
| `dither_strategy` | Required: `none`, `grid`, `snake`, `spiral`, `cross`, `jitter` | Pattern of small between-exposure pointing changes to move detector defects relative to the sky. |
| `dither_step_size_deg` | Optional degrees | Step magnitude when dithering. |
| `dither_steps` | Optional integer | Number of pattern steps. |
| `dither_position_angle_deg` | Optional degrees | Rotation of the dither pattern. |
| `min_fov_x_arcmin`, `min_fov_y_arcmin` | Optional arcminutes | Minimum delivered field; may require a multi-tile mosaic. |
| `max_fov_x_arcmin`, `max_fov_y_arcmin` | Optional arcminutes | Maximum delivered field; can be reached by subframing if the request permits and the instrument benefits. Each min must be ≤ its max where both are set. |
| `position_angle_deg` | Optional degrees | Rotation of delivered FOV X axis relative to RA; requires a compatible imager/rotator or orientation plan. |
| `min_pixel_scale_arcsec_per_px`, `max_pixel_scale_arcsec_per_px` | Optional arcsec/pixel | Hard acceptable effective pixel-scale window; constrains eligible camera readout/binning modes. |
| `min_pixels_per_fwhm` | Optional positive ratio | Seeing-relative minimum sampling. On an imager with `seeing_arcsec`, it imposes effective maximum scale `seeing_arcsec / min_pixels_per_fwhm`; inert if seeing is unknown. |
| `max_tiles` | Required; ORM default `1` | Maximum mosaic tile count. |
| `tile_overlap` | Required; ORM default `0.1` | Fractional overlap of adjacent tiles; `0.1` means ten percent. |
| `min_elevation_deg`, `max_elevation_deg` | Optional degrees | Target altitude bounds. |
| `min_sun_elevation_deg`, `max_sun_elevation_deg` | Optional degrees | Sun altitude bounds; the optical planner also applies a safety maximum of −10° regardless of a looser requested maximum. |
| `min_moon_separation_deg` | Optional degrees | Minimum target–Moon angular separation. |
| `min_moon_phase_fraction`, `max_moon_phase_fraction` | Optional fractions, 0–1 | Illumination window independent of separation. |
| `lunar_phase_direction` | Optional `any`, `waxing`, `waning` | Requested limb of the lunar cycle. The optical astroplan constraints use illumination but do not enforce direction there; code says scheduler-side date filtering is intended, yet no consumer was found in the inspected scheduler tree. Treat direction as unverified for execution. |
| `brightness_model` | Optional inline model | Source estimate used by `target_snr` and `target_full_well_fraction` exposure sizing. |
| `saturation_model` | Optional inline model | Brightest source/sky to protect; computes a per-frame exposure cap. Independent of the request's well-depth sizing target. |
| `brightness_model_id`, `saturation_model_id` | Optional integer IDs | Persisted links to existing brightness-model rows. Use inline create models for portable specs. |
| `image_normalization_settings_id` | Optional ID in SDK only | Legacy/auxiliary schema field. No matching optical configuration ORM column was found; do not rely on it for creation. |

The ORM also stores `saturation_level_fraction` (default `0.9`) as the maximum permitted fraction of camera full well for the saturation cap. **It is absent from the current `OpticalImagingConfiguration` create schema**, so the direct typed API cannot set it through this body; the ORM default applies unless another path updates it. This distinction matters because request `target_full_well_fraction` is a *depth target*, not that safety threshold. The FOV and sampling CHECKs are in the optical ORM. Optical altitude/Sun/Moon constraints and the −10° safety cap are built by `get_optical_target_observability_components()` in the same file.

### Brightness and saturation model fields

Inline create types live in [brightness-model create](../../../packages/py/skynet-sdk/skynet_sdk/schemas/brightness_model/create.py). `model_type=source` requires `magnitude_mag`; optional `filter_id` names its reference band, `is_point_source` defaults true, `av_mag` extinction defaults 0, `rv` defaults 3.1, and `temporal_component_id` / `spectral_component_id` can link existing variability/spectrum records. `magnitude_mag` is a point-source magnitude or extended-source surface brightness depending on `is_point_source`. `model_type=sky` has only the discriminator in its create shape. The ORM also knows a system-attached catalog-ephemeris model; this is not a general inline observer-create variant. For SNR/well sizing, a missing brightness model causes planning to fail. The saturation model can be omitted, in which case no model-based bright-source cap is computed.

## Optical-imaging request: every field

Source: [request create schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation_request/create.py), [stored request model](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py), and [base request model](../../../packages/py/skynet-db/skynet_db/models/observations/observations.py). The request's `request_type` discriminator is `optical_imaging` in Python and **also** `optical_imaging` as the JSON value of `requestType`. `ObservationRequestCreateBase` inherits some server-state fields; keep them out of ordinary create payloads.

| Field | Default / values | Meaning and practical effect |
|---|---|---|
| `request_type` | Required `optical_imaging` | Selects science optical request; bias/dark/flat calibration discriminators exist but are generated by the calibration scheduler for normal users. |
| `order` | Required integer | Traversal order among requests, subject to `sample_ordering`. |
| `sample_count` | `1` | Repeated temporal measurements of this request **per epoch**. It is not a frame count or requested depth. |
| `active` | `true` | Allows a request to participate without deleting it; false parks it. |
| `instrument_mode` | `none`; `include`, `exclude` | Per-request compatibility filter in the ORM. The current request-create schema has **no** `instrument_ids` member, so the direct nested create body cannot populate its include/exclude list; use observation-wide `instrument_mode`/`instrument_ids` for a new optical observation. |
| `filter_specifier_ids` | `null` | Ordered filter or filter-group IDs, resolved against wheel contents of a candidate imager. Unknown IDs raise at persistence. A group supplies alternatives; multiple specifiers form combinations. |
| `exposure_time_sec` | `null`, seconds | Explicit total exposure duration. Used as-is as the selected sizing mode across instruments. |
| `target_snr` | `null`, ratio | Solve total exposure per candidate imager from brightness model, sky brightness, readout noise, dark current, pixel scale and seeing. |
| `target_full_well_fraction` | `null`, fraction | Solve total exposure so the target reaches a fraction of sensor well; distinct from the configuration's saturation cap. |
| `allow_coadding` | ORM default `true` | Permit multiple shorter frames to reach dynamic requested depth when tracking or saturation limits one frame. |
| `allow_registration` | ORM default `false` | Reduce/align component frames before coaddition. |
| `allow_binning` | `null` | Permit camera binning beyond its default mode. Still bounded by pixel-scale and seeing-relative sampling limits. |
| `allow_subframe` | `null` | Permit a readout window down to the configuration's max FOV when useful. Inert without a max FOV; node may decline if no speed gain. |
| `allow_fast_readout` | `null` | Permit high-speed, higher-read-noise modes. False/null filters them out of the eligible set. |
| `electronic_shutter` | `null` | If set, require a camera whose electronic-shutter capability equals the requested boolean. |
| `global_shutter` | `null` | If set, require camera global-shutter capability equal to the requested boolean. |
| `min_bit_depth`, `max_bit_depth` | `null`, bits | Hard camera readout-mode bit-depth window. |
| `optimize_for` | `null`; `resolution`, `readout_speed` | Rank already-eligible readout modes for finest effective pixel scale or shortest readout time. Null prefers the camera default if eligible. An explicit objective can move away from the default. |
| `rbi_flood` | `null` | Preference/capability filter for residual-bulk-image flooding behavior in readout mode selection. |
| `high_gain` | `null` | Select/prefer a high-gain versus low-gain readout mode where available. |
| `hdr` | `null` | Select/prefer high-dynamic-range readout where available. |

The inherited create fields `status` (active), `is_deleted` (false), `observation_id`, `created_on`, and `modified_on` exist for schema reuse, but they are lifecycle/linkage state rather than observation science inputs. `current_sample`, `progress_fraction`, task IDs and exposures appear on readback or generated tasks, not as request-create parameters. The database has a separate request-level instrument relationship, but the current nested create schema does not expose its ID list.

**Exposure exclusivity caveat.** Observer-facing documentation says to set exactly one of `exposure_time_sec`, `target_snr`, `target_full_well_fraction`. Follow that rule. In the code inspected, these are all nullable fields without an exactly-one Pydantic validator or database CHECK. `get_task_parameters()` chooses fixed time first, then SNR, then well fraction. Thus several supplied modes can silently shadow one another, while no supplied mode may fail during planning. The API guide's claim that a multi-mode request is rejected is not backed by these code paths. The planner caps total exposure and considers tracking/saturation for per-frame limits. Notably, its coadding branch currently requires a dynamic mode (`not self.exposure_time_sec`), so a fixed-time request is treated as one exposure even if `allow_coadding=true`.

## Optical calibrations and processing adjacent to creation

The request union also contains `optical_imaging_bias_calibration`, `optical_imaging_dark_calibration`, and `optical_imaging_flat_calibration`; [their typed create fields](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation_request/create.py) share `instrument_id`, `camera_id`, `readout_mode_id`, `required_frames`, `expires_on`, `ccd_temperature_c`, `temperature_band`. Dark adds `exposure_time_sec`; flat adds `filter_ids`, `target_full_well_fraction`, `min_exposure_time_sec`, `max_exposure_time_sec`. These are calibration-scheduler work, not science requests the editor offers. [Calibration scheduler](../../../services/calibration_scheduler/main.py) generates them to support optical reduction. A science observation's `render_settings` concerns displayed products, not camera acquisition or calibration policy. Its nested fields are `schema_version` (1), `normalization.background_percentile` (1), `midtone_percentile` (97.5), `saturation_percentile` (99.8), `stretch` (default `midtone`; also `asinh`, `gamma`, `log`, `sqrt`, `exp`, `square`, `sinh`, `arcsinh`), and `rendering.nan` (`black`, `white`, `transparent`; default black), `invert` (false), `colormap` (`gray`). See [render schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/render_settings.py).

## Telescope network: configured, legacy, and running

**Do not equate a seeded telescope, a public listing, `is_available=true`, and a currently working SkyNode.** The seed loader is development/initialization data. The public list endpoint filters on `is_public` but does not prove live connection or observing access; the [public telescope route](../../../apps/public-api/public_api/routers/public.py) and [live page route](../../../apps/public-api/public_api/routers/web/live.py) make that distinction visible. A telescope additionally needs an eligible queue/grant, compatible optical imager/filter/readout, feasible sky window, safe hardware, and a functioning controller to run a given observation.

The freshest explicit operational statement checked in this repository is the **2026-09-23 participant kickoff**: SkyNode is running regularly/nightly on **two telescopes, PROMPT-CTIO-6 and HSC**. They are the only telescopes this source establishes as regularly running on the *new platform* at that date. The [kickoff agenda](participant-kickoff-260923/agenda.md) calls its map of **102 optical and 11 radio telescopes a Year-3 goal**, not a present roster. A live production database/API status was not available for this report, so do not read the two-telescope statement as a live September 24 uptime probe.

The repository's [seed inventory](../../../tools/dev/reset-db/utils/observatories.py) defines **16 optical and 2 radio telescope records**. It is useful for understanding the framework's known instruments and site examples, but the seeder sets `is_available=true` on many rows and that flag alone is not evidence of live connection. The optical records are:

| Seed telescope | Seed observatory/site | Evidence of regular new-platform operation |
|---|---|---|
| Morehead | Morehead Observatory, North Carolina | Not established by the 2026-09-23 kickoff. |
| PROMPT-CTIO-2 | PROMPT-CTIO, Chile | Not established. |
| PROMPT-CTIO-5 | PROMPT-CTIO, Chile | Not established. |
| **PROMPT-CTIO-6** | PROMPT-CTIO, Chile | **Yes**, kickoff statement. |
| PROMPT-SSO-1 | PROMPT-SSO, Australia | Not established. |
| APUS-CDK24 | American Public University System Observatory, West Virginia | Not established. |
| R-COP | Perth Observatory, Australia | Not established. |
| DSO-14 | Dark Sky Observatory, North Carolina | Not established. |
| DSO-17 | Dark Sky Observatory, North Carolina | Not established. |
| RRRT | Fan Mountain Observatory, Virginia | Not established. |
| **HSC** | Hampden-Sydney College Observatory, Virginia | **Yes**, kickoff statement. |
| MDRS-WF | Mars Desert Research Station, Utah | Not established. |
| PROMPT-MO | Meckering Observatory, Australia | Not established. |
| NSO-17-CDK | Northern Skies Observatory, Vermont | Not established. |
| OAUJ-CDK500 | Jagiellonian University Observatory, Poland | Not established. |
| OAUJ-TYMCE | Tymce Observatory, Poland | Not established. |

The two seeded radio records are University of Tasmania 14 Meter at Mount Pleasant and GB 20m Telescope at Green Bank; they are outside optical scheduling. An older [2026-08-27 presentation CSV](presentation-260827/telescopes.csv) marks 12 **optical sites** and two radio sites `on_network_today=1`. Its optical sites are CTIO, Siding Spring, Morehead, Perth, Dark Sky, Fan Mountain, Jagiellonian University, Tymce, American Public University, Hampden-Sydney College, Northern Skies, and Mars Desert Research Station. That is site-level legacy/network planning data and includes more telescopes than the later, explicitly new-platform SkyNode claim. It must not be used as a live count of optical instruments on the current controller. For a current deployment check, query the production `/v1/public/telescopes` or authenticated `/v1/me/observing-access/telescopes`, then inspect telescope `isAvailable`, instruments, live mount/device snapshots, and queue access; a public row is only discoverability.

## Known mismatches and limits to watch

| Topic | Documentation or typed surface | Code-backed interpretation |
|---|---|---|
| Brightness location | Some [target guide](../../skynet_docs/observers/editor/02-target.md) prose still places brightness/saturation on `Target`. | They moved to `OpticalImagingConfiguration`; [target create schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/target/create.py) has neither. |
| Exposure exclusivity | [API guide](../../skynet_docs/developers/guides/creating-observations.md) says multiple modes are rejected. | [request ORM](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py) uses fixed > SNR > well precedence; no exactly-one check was found. |
| Request discriminator | Some [API guide](../../skynet_docs/developers/guides/creating-observations.md) examples use `"opticalImaging"`. | [ObservationType](../../../packages/py/skynet-sdk/skynet_sdk/enums.py) and [OpenAPI](../../skynet_docs/openapi-observation.yaml) use `"optical_imaging"`; only the key `requestType` is camelCase. |
| Saturation threshold | ORM has `saturation_level_fraction=0.9`. | Current [optical create schema](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/base.py) does not expose it. |
| Moon phase direction | Configuration stores waxing/waning. | The optical constraint builder explicitly skips direction; scheduler enforcement was not found in the inspected tree. |
| Frame-level cohesion | Enum offers `frame`. | [scheduler grouping](../../../services/cp_sat_task_scheduler/main.py) treats it like `sample`; no partial sample across windows. |
| Cadence and coordination | All kinds and synchronized copies can be stored. | Epoch-level gap/period code exists; finer levels and synchronized starts are not established as fully enforced. |
| Telescope counts | Seeder/public flags, 2026-08-27 network CSV, and 2026-09-23 kickoff give different counts. | They describe different scopes: configured rows, legacy site map, and regular new-platform operation, respectively. |

## Source map for future updates

- **Creation and edit:** [entity POST](../../../apps/public-api/public_api/routers/entities/observations.py), [spec validate/plan/publish/apply](../../../apps/public-api/public_api/routers/observation_specs.py), [React editor routes](../../../apps/website-react/app/routes/observe), [portable spec builder](../../../packages/py/skynet-db/skynet_db/specs.py).
- **Schemas and values:** [observation create](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/create.py), [observation spec](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation_spec.py), [optical configuration](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation/base.py), [request create](../../../packages/py/skynet-sdk/skynet_sdk/schemas/observation_request/create.py), [target create](../../../packages/py/skynet-sdk/skynet_sdk/schemas/target/create.py), [enums](../../../packages/py/skynet-sdk/skynet_sdk/enums.py).
- **Storage and execution:** [Observation/Request ORM](../../../packages/py/skynet-db/skynet_db/models/observations/observations.py), [optical ORM and exposure planner](../../../packages/py/skynet-db/skynet_db/models/observations/optical_imaging_observations.py), [target ORM](../../../packages/py/skynet-db/skynet_db/models/observations/targets.py), [result materializer](../../../services/observation_result_materializer/main.py), [CP-SAT scheduler](../../../services/cp_sat_task_scheduler/main.py), [new scheduler cadence](../../../services/scheduler/preprocessing/policies/cadence_plan.py).
- **Fleet evidence:** [seeded observatories](../../../tools/dev/reset-db/utils/observatories.py), [2026-09-23 kickoff](participant-kickoff-260923/agenda.md), [2026-08-27 site CSV](presentation-260827/telescopes.csv), [public telescope API](../../../apps/public-api/public_api/routers/public.py).
