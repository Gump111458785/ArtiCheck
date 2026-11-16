export const activeExecution=status=>['queued','starting','running','cancelling'].includes(status);

export function reviewControlState(project,{inFlight=false,running=false,preparing=false}={}){
 const report=project?.online_report,execution=report?.execution;
 const terminated=Boolean(report?.terminated_at);
 const intent=project?.online_control_request||(report?.termination_requested?'terminate':'pause');
 const pendingReview=project?.online_pending_request;
 const pendingExecution=project?.online_execution_pending;
 const pending=Boolean(
  pendingReview&&pendingReview.id!==report?.id||
  pendingExecution&&(!execution||execution.attempt_id===pendingExecution.retry_of)
 );
 const serverActive=report?.status==='reviewing'||activeExecution(execution?.status);
 const active=Boolean(running||pending||serverActive);
 const retry=!terminated&&!inFlight&&active&&Boolean(
  project?.online_cancel_error||project?.online_control_request&&execution?.status!=='cancelling'
 );
 const stopping=!terminated&&!retry&&Boolean(inFlight||execution?.status==='cancelling');
 const paused=!terminated&&!stopping&&!active&&(
  project?.online_paused??(report?.status==='cancelled'||execution?.status==='cancelled')
 );
 return {intent,terminated,retry,stopping,paused,preparing:preparing||Boolean(project?.online_upload_pending&&!running&&!serverActive),
  running:!terminated&&!paused&&!stopping&&active};
}

export function reviewControlButtons(state,attribute){
 if(state.terminated||state.preparing||state.stopping)return '';
 const button=(action,label,tone)=>`<button type="button" class="btn small review-control review-control-${tone}" ${attribute(action)}>${label}</button>`;
 if(state.retry){
  if(state.intent==='pause')return button('pause','暂停','pause')+button('terminate-review','中断','stop');
  return button('retry-control','重试中断','stop');
 }
 return (state.running?button('pause','暂停','pause'):state.paused?button('continue-review','继续','continue'):'')+
  (state.running||state.paused?button('terminate-review','中断','stop'):'');
}
