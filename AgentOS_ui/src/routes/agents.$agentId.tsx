import { createFileRoute } from '@tanstack/react-router';
import { AgentConfiguration } from '@/components/agentos/agents';
export const Route = createFileRoute('/agents/$agentId')({head:()=>({meta:[{title:'Agent configuration · AgentOS'},{name:'description',content:'Fine-tune your agent identity, behavior, knowledge, tools, guardrails, and budget.'},{property:'og:title',content:'Agent configuration · AgentOS'},{property:'og:description',content:'Good defaults. Fine-tuned to your world.'},{property:'og:type',content:'website'},{name:'twitter:card',content:'summary_large_image'}]}),component:AgentEditor});
function AgentEditor(){const {agentId}=Route.useParams();return <AgentConfiguration key={agentId} agentId={agentId}/>;}
