import { createFileRoute } from '@tanstack/react-router';
import { Payment } from '@/components/agentos/payment';
export const Route = createFileRoute('/payment')({head:()=>({meta:[{title:'Add funds · AgentOS'},{name:'description',content:'Fund your shared AgentOS wallet with a clear, simple checkout.'},{property:'og:title',content:'Add funds · AgentOS'},{property:'og:description',content:'Fund your shared AgentOS wallet with a clear, simple checkout.'},{property:'og:type',content:'website'},{name:'twitter:card',content:'summary_large_image'}]}),component:Payment});
