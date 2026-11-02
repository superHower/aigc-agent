import { Alert, Button } from 'antd'
import { Link } from 'react-router-dom'

export function FrozenCreditsNotice({ amount, taskId }: { amount: number; taskId?: string }) {
  if (amount <= 0) return null
  return <Alert
    showIcon
    type="info"
    style={{ marginTop: 12, marginBottom: 12 }}
    message={`${amount} 积分正在为生成任务预留，尚未正式扣除`}
    description="请等待任务完成：生成成功后扣费，最终失败或取消的部分会在任务结束后自动释放。暂时不需要生成时，可进入任务页面取消任务，并等待取消处理完成。会员积分若已到期，释放后会自动作废；任务结束后积分仍未释放，请联系客服并提供任务编号。"
    action={<Link to={taskId ? `/tasks/${taskId}` : '/tasks'}><Button size="small">查看任务进度</Button></Link>}
  />
}
