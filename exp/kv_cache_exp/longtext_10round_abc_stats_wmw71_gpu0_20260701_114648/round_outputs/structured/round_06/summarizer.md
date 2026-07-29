[Round 6 Deliverable]
@round[6] @feature_scope[supply_items] @depends_on[1,2,3,4,5] @new_systems[supply,battery,shield_cell,parcel_wrap] @deliverable[incremental_spec]

### 供应系统设计
1. **补给站触发**：玩家移动至supply tile时自动触发，一次性使用，恢复值为当前上限的50%（如stamina上限100恢复50点）
2. **道具库存**：最多携带2个道具，不占货舱槽位
3. **道具机制**：
   - battery：恢复stamina至上限（不超限）
   - shield_cell：恢复shield至上限（不超限）
   - parcel_wrap：保护一个fragile包裹免受一次storm伤害
4. **使用时机**：手动使用（通过快捷键调用），非自动触发
5. **测试点**：
   - 补给站触发后stamina恢复50%（测试1）
   - 携带2个道具时无法再获取新道具（测试2）
   - parcel_wrap在storm tile时保护包裹（测试3）
   - 使用battery后stamina不超上限（测试4）
   - shield_cell恢复至shield上限（测试5）
   - 多次使用supply tile是否重置道具库存（测试6）
   - 道具保护仅限一次storm伤害（测试7）
   - 携带道具不影响货舱容量（测试8）

```json
{
  "ok": true,
  "round": 6,
  "task_id": 9006,
  "tag_hits": {
    "@round": true,
    "@feature_scope": true,
    "@depends_on": true,
    "@