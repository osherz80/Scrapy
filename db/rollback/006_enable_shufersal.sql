-- Return Shufersal to its pre-recovery state; existing products are untouched.
UPDATE public.chains SET enabled = false WHERE id = 'shufersal';
