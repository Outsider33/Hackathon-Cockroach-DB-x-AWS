-- Seed data -- FOURTEEN REAL BELIEF REVISIONS.
--
-- None of this is synthetic. Every row comes from a dated engineering log in a
-- private repository, where an AI agent and its author spent two weeks running
-- a generative-CAD -> meshing -> FEA -> fatigue pipeline. Every revision is a
-- moment where the agent was wrong, found out, and recorded what changed its
-- mind.
--
-- The failure modes are the interesting part: a fatigue criterion blind to
-- stress reversal, an optimiser that had been dead and silent for two runs,
-- a symmetric convergence tolerance that accepted a design failing by 4%, and
-- a submission repository that returned 404 to anyone but its owner.

USE agentmem;

-- ---------------------------------------------------------------------------
-- What was believed, until it wasn't. Closed intervals.
-- ---------------------------------------------------------------------------
INSERT INTO belief (key, value, status, source, valid_from, valid_to) VALUES
('hub_barrel_manufacturable', 'the hub barrel geometry is manufacturable', 'ESTABLISHED', 'CAD pipeline, run of 2026-07-20', '2026-07-20 00:00:00+00', '2026-07-26 00:00:00+00'),
('convergence_criterion',     'the sizing loop converges on the static criterion', 'ESTABLISHED', 'survival.py, before 2026-07-26', '2026-07-20 00:00:00+00', '2026-07-26 00:00:00+00'),
('pocket_count',              'the lightening optimiser produces pockets', 'ESTABLISHED', 'assumed from the code being present', '2026-07-20 00:00:00+00', '2026-07-26 00:00:00+00'),
('fatigue_amplitude_basis',   'sigma_a = ( VM(Sigma_max) - VM(Sigma_min) ) / 2', 'ESTABLISHED', 'goodman(), scalar formulation', '2026-07-20 00:00:00+00', '2026-07-31 00:00:00+00'),
('part_thickness',            '11.53 mm', 'ESTABLISHED', 'FEA run, scalar fatigue criterion', '2026-07-26 00:00:00+00', '2026-07-31 00:00:00+00'),
('part_mass',                 '5.494 kg', 'ESTABLISHED', 'FEA run, scalar fatigue criterion', '2026-07-26 00:00:00+00', '2026-07-31 00:00:00+00'),
('fatigue_safety_factor',     '1.74', 'ESTABLISHED', 'FEA run, scalar fatigue criterion', '2026-07-26 00:00:00+00', '2026-07-31 00:00:00+00'),
('governing_cycle',           'left/right inversion: outer wheel <-> inner wheel', 'ESTABLISHED', 'physical reasoning, not swept', '2026-07-26 00:00:00+00', '2026-07-31 00:00:00+00'),
('stop_tolerance',            'abs(demand - 1) < 0.05, symmetric', 'ESTABLISHED', 'tightened the same morning', '2026-07-31 00:00:00+00', '2026-07-31 12:00:00+00'),
('caliper_datasheet',         'not found -- 191 catalogue PDFs downloaded, none contains the selected caliper', 'NOT_FOUND', 'manufacturer catalogue sweep', '2026-07-28 00:00:00+00', '2026-07-29 00:00:00+00'),
('strobe_cause',              'video encoding defect', 'ESTABLISHED', 'five encoding fixes attempted, one made it worse', '2026-07-31 00:00:00+00', '2026-08-01 00:00:00+00'),
('displayed_rod_spacing',     '292.1 mm, retyped into the overlay by hand', 'ESTABLISHED', 'video overlay, v3', '2026-07-31 00:00:00+00', '2026-08-01 00:00:00+00'),
('submission_repo_public',    'the repository linked in the end card is public', 'ESTABLISHED', 'assumed, never clicked', '2026-07-28 00:00:00+00', '2026-08-01 00:00:00+00'),
('contest_criteria',          'five criteria, equally weighted', 'ESTABLISHED', 'assumed from the landing page', '2026-07-27 00:00:00+00', '2026-08-02 00:00:00+00');

-- ---------------------------------------------------------------------------
-- What is believed now -- including, explicitly, what is not known.
-- Open intervals.
-- ---------------------------------------------------------------------------
INSERT INTO belief (key, value, status, source, valid_from, valid_to) VALUES
('hub_barrel_manufacturable', 'NOT manufacturable -- bearing spacing wrong, +1.7 kg of dead metal', 'ESTABLISHED', 'REPRISE.md sec.0', '2026-07-26 00:00:00+00', NULL),
('convergence_criterion',     'the most demanding of the two: static OR fatigue', 'ESTABLISHED', 'REPRISE.md sec.3.4', '2026-07-26 00:00:00+00', NULL),
('pocket_count',              '0 pockets -- the optimiser was dead and silent for two full runs', 'ESTABLISHED', 'REPRISE.md sec.3.5', '2026-07-26 00:00:00+00', NULL),
('fatigue_amplitude_basis',   'sigma_a = VM( Sigma_max - Sigma_min ) / 2, on the amplitude TENSOR', 'ESTABLISHED', 'REPRISE.md sec.3.7', '2026-07-31 00:00:00+00', NULL),
('part_thickness',            '14.00 mm', 'ESTABLISHED', 'FEA run, tensor fatigue criterion', '2026-07-31 00:00:00+00', NULL),
('part_mass',                 '6.007 kg', 'ESTABLISHED', 'FEA run, tensor fatigue criterion', '2026-07-31 00:00:00+00', NULL),
('fatigue_safety_factor',     '1.51', 'ESTABLISHED', 'FEA run, tensor fatigue criterion', '2026-07-31 00:00:00+00', NULL),
('governing_cycle',           '8g bump <-> 1.5g cornering with load transfer -- two ORTHOGONAL load cases', 'ESTABLISHED', 'REPRISE.md sec.3.7, sweep of all 15 state pairs', '2026-07-31 00:00:00+00', NULL),
('stop_tolerance',            '0.95 <= demand <= 1.0 -- converge from the safe side only', 'ESTABLISHED', 'REPRISE.md sec.3.8', '2026-07-31 12:00:00+00', NULL),
('caliper_datasheet',         'radius 21.45 mm -- found on a reseller product page, not in any catalogue', 'ESTABLISHED', 'reseller product page', '2026-07-29 00:00:00+00', NULL),
('strobe_cause',              'a scene object -- the ground plane. Removing it removed the flicker.', 'ESTABLISHED', 'ablation test, 2 minutes', '2026-08-01 00:00:00+00', NULL),
('displayed_rod_spacing',     '220.0 mm -- read from the spec file at render time', 'ESTABLISHED', 'overlay.py, values read not retyped', '2026-08-01 00:00:00+00', NULL),
('submission_repo_public',    'PRIVATE -- a judge following the link would have got a 404', 'ESTABLISHED', 'clicked from a logged-out browser', '2026-08-01 00:00:00+00', NULL),
('contest_criteria',          '25% documentation, 20% API reports, 20% technical, 15% UI, 20% creativity', 'ESTABLISHED', 'the actual rules page, copied into the repo', '2026-08-02 00:00:00+00', NULL),
('mesh_independence',         'two runs of the same commit return 14.00 mm and 13.28 mm -- unexplained', 'UNDECIDABLE', 'mesh size was slaved to thickness: the instrument changed with the measurement', '2026-07-31 00:00:00+00', NULL),
('published_numbers_checked', '???', 'UNDECIDABLE', 'coherence.py -- no explicit run marker in the prose to check against', '2026-07-28 00:00:00+00', NULL),
('additive_fatigue_data',     'not found -- no qualification dataset for this alloy and process', 'NOT_FOUND', 'literature sweep, 2026-07-25', '2026-07-25 00:00:00+00', NULL);

-- ---------------------------------------------------------------------------
-- What changed the agent's mind. Pairing by key: the closed interval is the
-- old belief, the open interval is the new one.
-- ---------------------------------------------------------------------------
INSERT INTO revision (belief_old, belief_new, occurred_at, evidence, evidence_source)
SELECT o.id, n.id, n.valid_from,
  CASE o.key
    WHEN 'hub_barrel_manufacturable' THEN 'Direct check of the bearing spacing against the supplier drawing: the barrel could not be machined as modelled, and carried 1.7 kg of metal that no load case needs.'
    WHEN 'convergence_criterion'     THEN 'The loop was converging on whichever criterion it was told to watch, not on the one that governs. Swept both; fatigue governs here.'
    WHEN 'pocket_count'              THEN 'The run log printed n_poches = 0 for two consecutive runs and nobody read it. The optimiser had been dead the whole time.'
    WHEN 'fatigue_amplitude_basis'   THEN 'Von Mises carries no sign, so two opposite bending states look identical to it and a full stress reversal reads as zero amplitude. Checked on an analytic case (+174.7 <-> -17.5 MPa): sigma_a = 96.1 instead of 78.6, an 18% underestimate.'
    WHEN 'part_thickness'            THEN 'Consequence of the tensor fatigue criterion. The part had to grow by 2.47 mm to keep the same safety factor.'
    WHEN 'part_mass'                 THEN 'Consequence of the tensor fatigue criterion: +513 g. A full day of weight optimisation was cancelled -- the 5.494 kg had never existed.'
    WHEN 'fatigue_safety_factor'     THEN 'The previous 1.74 was computed on an amplitude that ignored stress reversal. Real value 1.51, still above the 1.50 target but with no margin left.'
    WHEN 'governing_cycle'           THEN 'Sweeping all 15 state pairs instead of the hard-coded pair found a worse cycle than the left/right inversion. The reasoning was right in principle and wrong about the culprit -- which is exactly why you sweep instead of assume.'
    WHEN 'stop_tolerance'            THEN 'A symmetric tolerance accepts demand = 1.042, i.e. a design that FAILS by 4%. Observed: the loop stopped at 12.44 mm with SF 1.44 against 1.50 required.'
    WHEN 'caliper_datasheet'         THEN '191 catalogue PDFs downloaded, none containing the selected caliper. The answer came from a reseller product page. The single most decisive document in the corpus was named 0901d19680537e49_pdf_preview_medium.pdf.'
    WHEN 'strobe_cause'              THEN 'After the same defect was reported twice, stop fixing and start removing: deleting the ground plane removed the flicker. Five encoding fixes had targeted the wrong layer, and one of them made it worse.'
    WHEN 'displayed_rod_spacing'     THEN 'The overlay showed 292.1 mm while the spec had said 220.0 since the previous day -- in the very shot where the voiceover claims every number comes from the file.'
    WHEN 'submission_repo_public'    THEN 'Clicked the link from a logged-out browser on the day of publication: 404. The submission would have been ineligible, and it was found by accident.'
    WHEN 'contest_criteria'          THEN 'Read the actual rules page instead of the landing page. Two deliverables had been treated as mandatory that were not required at all, and the one that was mandatory had been missed.'
  END,
  CASE
    WHEN o.key IN ('hub_barrel_manufacturable','convergence_criterion','pocket_count','fatigue_amplitude_basis','part_thickness','part_mass','fatigue_safety_factor','governing_cycle','stop_tolerance') THEN 'CAD_Pipeline/REPRISE.md'
    ELSE 'CLAUDE.md, protocols P1 to P7'
  END
FROM belief o JOIN belief n ON o.key = n.key
WHERE o.valid_to IS NOT NULL AND n.valid_to IS NULL;

-- ---------------------------------------------------------------------------
-- The open questions. These are not failures of the memory, they are its
-- output. Each one is copied from a hand written registry in the source
-- project, where somebody had to maintain it by hand.
-- ---------------------------------------------------------------------------
INSERT INTO belief (key, value, status, source, valid_from, valid_to) VALUES
('brake_disc_mass_kg',     'estimated 4.0 kg by interpolation -- three rotors quoted by the manufacturer, none is ours (0.81 in thickness against .72 on our caliper sheet)', 'NOT_FOUND', 'BESOINS_DONNEES.md sec.1.5 -- the field is literally null', '2026-07-29 00:00:00+00', NULL),
('rod_end_type',           'uniball or tapered rod end -- the bore is 20 mm in one case and 54 mm in the other. Architecture decision, not a lookup.', 'UNDECIDABLE', 'BESOINS_DONNEES.md sec.2.2', '2026-07-27 00:00:00+00', NULL),
('hub_bore_radius_mm',     '45 mm, to be confirmed -- drives local mass, not strength (bearing crush is at 7% of ULS)', 'UNDECIDABLE', 'BESOINS_DONNEES.md sec.2.4, marked non-blocking', '2026-07-27 00:00:00+00', NULL),
('hub_barrel_architecture','A or B -- the largest single item left, 1.0 to 1.7 kg at stake', 'UNDECIDABLE', 'REPRISE.md sec.6, item 1', '2026-07-26 00:00:00+00', NULL),
('front_wheel',            'Ultra X103 5452BL, 15x4 in, 5 on 205 mm VW, backspace 50.8 mm, offset -12 mm, 7.44 kg', 'ESTABLISHED', 'BESOINS_DONNEES.md sec.2.3, closed 2026-07-27', '2026-07-27 00:00:00+00', NULL),
('lateral_g',              '1.5 -- conservative by construction: mu falls as Fz rises, so the load is overestimated', 'ESTABLISHED', 'tyre adhesion note, source Guiggiani. Flagged TO CONFIRM for weeks, and never actually a gap.', '2026-07-28 00:00:00+00', NULL),
('disc_radius_mm',         'dead input -- traced through the code, it enters no calculation (braking torque is wheel radius x Fx)', 'ESTABLISHED', 'BESOINS_DONNEES.md sec.3', '2026-07-28 00:00:00+00', NULL),
('surface_treatment',      'none -- shot peening is wired and disabled by default, K_V = 1.00', 'ESTABLISHED', 'enabling it gives +15% on the fatigue limit, worth 0.3 to 0.5 kg. Two hours to test.', '2026-07-30 00:00:00+00', NULL);

-- ---------------------------------------------------------------------------
-- What the agent knows how to compute, and what each calculation needs.
-- ---------------------------------------------------------------------------
INSERT INTO computation (name, purpose, standard, cost_note) VALUES
('fea_run',              'Full mesh + solve + resize loop on the front upright', NULL, 'about 2 hours on the current machine'),
('fatigue_check_parent', 'Fatigue of the parent metal on the amplitude tensor', 'Crossland / Goodman', 'seconds, once the run has produced tensors'),
('fatigue_check_welded', 'Fatigue of the welded assemblies', 'EN 1993-1-9', 'seconds'),
('bolt_check',           'Bolted joint check', 'ISO 898-1 / EN 1993-1-8', 'seconds'),
('unsprung_mass_budget', 'Unsprung mass budget for the front corner', NULL, 'minutes, but only if every mass is known'),
('scrub_recompute',      'Recompute scrub radius from wheel offset and rod end spacing', NULL, 'minutes'),
('rod_end_boss_sizing',  'Size the rod end boss and its local mass', NULL, 'minutes');

INSERT INTO requirement (computation_id, belief_key, criticality, why)
SELECT c.id, v.k, v.crit, v.why FROM computation c JOIN (VALUES
 ('fea_run','mesh_independence','BLOCKING','If mesh size is slaved to thickness, the instrument changes with the measurement and the result cannot be compared across iterations.'),
 ('fea_run','hub_barrel_architecture','BLOCKING','The geometry cannot be generated until A or B is chosen.'),
 ('fea_run','surface_treatment','DEGRADES','Sets K_V. Wrong value shifts the converged thickness by about 0.9 mm.'),
 ('fatigue_check_parent','fatigue_amplitude_basis','BLOCKING','Scalar amplitude is blind to stress reversal. Established as of 2026-07-31.'),
 ('fatigue_check_parent','governing_cycle','BLOCKING','Which pair of load states governs. Hard-coding it hides worse cycles.'),
 ('fatigue_check_parent','additive_fatigue_data','DEGRADES','No qualification dataset for this alloy and process. The check runs, its absolute value does not transfer to an additive part.'),
 ('fatigue_check_welded','lateral_g','BLOCKING','Sets the cornering load case.'),
 ('bolt_check','rod_end_type','BLOCKING','Uniball or tapered changes the bore from 20 to 54 mm, so it changes the joint entirely.'),
 ('unsprung_mass_budget','brake_disc_mass_kg','BLOCKING','Estimated, not measured. The budget reads 27.25 kg known out of 40 declared, so an estimate here can hide an overrun.'),
 ('unsprung_mass_budget','front_wheel','BLOCKING','7.44 kg, closed on 2026-07-27.'),
 ('unsprung_mass_budget','hub_bore_radius_mm','DEGRADES','Drives local mass only, not strength.'),
 ('scrub_recompute','front_wheel','BLOCKING','Offset is what places the contact patch.'),
 ('scrub_recompute','disc_radius_mm','COSMETIC','Kept in the spec, enters no calculation. Listed so nobody goes looking for it again.'),
 ('rod_end_boss_sizing','rod_end_type','BLOCKING','Nothing about the boss can be sized before this decision.'),
 ('rod_end_boss_sizing','hub_barrel_architecture','DEGRADES','Changes the surrounding envelope.')
) AS v(cname,k,crit,why) ON c.name = v.cname;
