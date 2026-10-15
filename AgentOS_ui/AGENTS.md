<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

## AgentOS structure
- Keep UI-only workspace data in `src/lib/agentos/mockData.ts` and shared in-memory state in `store.tsx`; this makes future AgentOS API replacement explicit without implying real payments or connections.
- Use independent leaf routes for each product screen and shared interface modules in `src/components/agentos`; the root provides workspace state and the common shell, excluding standalone onboarding and checkout.
- Define all AgentOS visual styling and semantic colors in `src/styles.css`; this preserves one consistent precision-oriented design system.
