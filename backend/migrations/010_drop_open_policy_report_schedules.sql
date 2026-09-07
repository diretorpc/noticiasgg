-- 07/09/2026 — remove a policy que dava a QUALQUER usuário logado (role
-- authenticated) leitura e escrita em todas as linhas de report_schedules.
-- Ninguém legítimo usa esse caminho: o painel só fala com o backend, e o
-- backend usa service_role, que ignora RLS. RLS continua ligado; sem policy,
-- authenticated e anon não enxergam nada.
--
-- Aplicar uma vez, via `supabase db query --linked` (Management API).
-- Reversão (só se algum consumidor com JWT aparecer):
--   create policy "authenticated full access report_schedules"
--     on public.report_schedules for all to authenticated
--     using (true) with check (true);
drop policy if exists "authenticated full access report_schedules"
  on public.report_schedules;
